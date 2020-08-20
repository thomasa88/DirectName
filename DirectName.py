#Author-Thomas Axelsson
#Description-Shows a naming dialog directly after creating a feature.

# This file is part of DirectName, a Fusion 360 add-in for naming
# features directly after creation.
#
# Copyright (c) 2020 Thomas Axelsson
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import adsk.core, adsk.fusion, adsk.cam, traceback

# Text Commands. Python version.
# neu_dev.list_functions()
import neu_server
import neu_modeling

import os
import re
import sys

### TODO:
### Option to name new bodies, views etc?

NAME = 'Direct Name'

FILE_DIR = os.path.dirname(os.path.realpath(__file__))

# Must import lib as unique name, to avoid collision with other versions
# loaded by other add-ins
from .thomasa88lib import utils
from .thomasa88lib import events
from .thomasa88lib import timeline
from .thomasa88lib import manifest
from .thomasa88lib import error

# Force modules to be fresh during development
import importlib
importlib.reload(thomasa88lib.utils)
importlib.reload(thomasa88lib.events)
importlib.reload(thomasa88lib.timeline)
importlib.reload(thomasa88lib.manifest)
importlib.reload(thomasa88lib.error)

class RenameType:
    API = 1
    TEXT_COMMAND = 2

class RenameInfo:
    def __init__(self, label, name_obj, select_obj, rename_type=RenameType.API):
        self.label = label
        self.name_obj = name_obj
        self.select_obj = select_obj
        self.rename_type = rename_type

SET_NAME_CMD_ID = 'thomasa88_setFeatureName'

# Heuristic to find new bodies
UNNAMED_BODY_PATTERN = re.compile('Body\d+')

app_ = None
ui_ = None

error_catcher_ = thomasa88lib.error.ErrorCatcher(msgbox_in_debug=False)
events_manager_ = thomasa88lib.events.EventsManager(error_catcher_)
manifest_ = thomasa88lib.manifest.read()

need_init_ = True
last_flat_timeline_ = None
rename_cmd_def_ = None
rename_objs_ = None
command_terminated_handler_info_ = None

def workspace_activated_handler(args: adsk.core.WorkspaceEventArgs):
    global need_init_

    if ui_.activeWorkspace.id == 'FusionSolidEnvironment':
        # DocumentActivated is not always triggered (2020-07-27), so we mark
        # that we need an update here, but it will actually trigger on the
        # first command. (The timeline is not ready on in this event.)
        # Bug: https://forums.autodesk.com/t5/fusion-360-api-and-scripts/api-bug-application-documentactivated-event-do-not-raise/m-p/9020750
        need_init_ = True
        enable()

def workspace_pre_deactivate_handler(args: adsk.core.WorkspaceEventArgs):
    disable()

def enable():
    global command_terminated_handler_info_
    if not command_terminated_handler_info_:
        command_terminated_handler_info_ = events_manager_.add_handler(ui_.commandTerminated,
                                            callback=command_terminated_handler)

def disable():
    global command_terminated_handler_info_
    if command_terminated_handler_info_:
        command_terminated_handler_info_ = events_manager_.remove_handler(command_terminated_handler_info_)

def command_terminated_handler(args: adsk.core.ApplicationCommandEventArgs):
    #if ui_.activeWorkspace.id != 'FusionSolidEnvironment':
    #    # Only for the Design workspace
    #    return
    
    #print("TERM", args.commandId, args.terminationReason, app_.activeEditObject.classType())

    global need_init_
    if need_init_:
        check_timeline(init=True)
        need_init_ = False
        return

    if args.terminationReason != adsk.core.CommandTerminationReason.CompletedTerminationReason:
        return

    # Heavy traffic commands
    if args.commandId in ['SelectCommand', 'CommitCommand']:
        return

    if args.commandId == SET_NAME_CMD_ID:
        # self
        return

    if app_.activeEditObject.classType() == 'adsk::fusion::Sketch':
        # Don't activate inside Sketch edit mode, e.g. when the user deletes a line or
        # runs a Mirror command.
        # Alternative: Track SketchActivate, SketchStop and UndoCommand (note that
        # CompletedTerminationReason == Cancel). Or possibly ActivateEnvironmentCommand.
        return

    # E.g. when creating a Box, the command will terminate after creating the
    # sketch, but it wants to immediately fire a new command. The problem is
    # that we get the terminated event first (registered last?), so we block
    # the next command.
    # Therefore, let's put ourselves at the end of the event queue.
    events_manager_.delay(lambda: after_terminate_handler(args.commandId))

def after_terminate_handler(command_id):
    global need_init_
    global rename_objs_
    # Check that the user is not active in another command
    if not ui_.activeCommand or ui_.activeCommand == 'SelectCommand':
        if command_id == 'FusionHalfSectionViewCommand':
            analysis_entity_id = neu_server.get_entity_id("VisualAnalyses")
            child_count = neu_modeling.get_child_count(analysis_entity_id)
            # Most likely the last child is the new one(?)
            for i in range(child_count - 1, -1, -1):
                # neu_server.get_user_name() always gives a name
                # properties['userName'] is empty if the user has not set it
                # properties['creationIndex'] is the default index. E.g. In Section3 index is 3.
                section_id = neu_modeling.get_child(analysis_entity_id, i)['entityId']
                section_properties = neu_server.get_entity_properties(section_id)
                if section_properties['userName'] == '':
                    rename_info = RenameInfo("Section", section_id, section_id, RenameType.TEXT_COMMAND)
                    rename_objs_ = [ rename_info ]
                    rename_cmd_def_.execute()
                    break
        else:
            rename_objs_ = check_timeline()
            if rename_objs_:
                rename_cmd_def_.execute()

def check_timeline(init=False):
    global last_flat_timeline_
    #print("CHECK", not init)
    rename_objs = []

    status, timeline = thomasa88lib.timeline.get_timeline()
    if status != thomasa88lib.timeline.TIMELINE_STATUS_OK:
        return

    # User can expand/collapse the timeline groups without us knowing,
    # and it affects the timeline API structure, so get a flat timeline.
    current_flat_timeline = thomasa88lib.timeline.flatten_timeline(timeline)

    if not init:
        # Doing Undo (Ctrl+Z) goes by unnoticed, so we can't rely on length
        # to detect change.
        # However, we know that the last addition should be just before the
        # rollback bar.
        last_new_obj = None
        index = 0
        for next_index, next_obj in enumerate(current_flat_timeline):
            if next_obj.isRolledBack:
                break
            index = next_index
            last_new_obj = next_obj
        
        if last_new_obj:
            # The user cannot name two timeline objects the same thing, but they
            # can do create, undo, create and get a new object with the exact
            # same name, making us miss it, if we go by name.
            
            # If an object is dragged in the timeline, we won't find it in the same place,
            # but it is not a new object - so search the whole old timeline.

            # Sketch + Solid/Feature is possible. New N components from N bodies
            # are possible as well. Try to catch both.
            # Search backwards until we recognize an object from earlier.
            new_objs = []
            for obj in reversed(current_flat_timeline[0:index+1]):
                is_old = any(o == obj for o in last_flat_timeline_)
                if is_old:
                    break
                new_objs.append(obj)

            if new_objs:
                # Creation order
                new_objs.reverse()

                for timeline_obj in new_objs:
                    # Can't access entity of all timeline objects
                    # Bug: https://forums.autodesk.com/t5/fusion-360-api-and-scripts/api-bug-cannot-access-entity-of-quot-move-quot-feature/m-p/9651921
                    try:
                        entity = timeline_obj.entity
                    except RuntimeError:
                        entity = None
                    if entity:
                        entity_type = thomasa88lib.utils.short_class(timeline_obj.entity)
                        label = entity_type.replace('Feature', '')
                        if entity_type == 'Occurrence':
                            occur_type = thomasa88lib.timeline.get_occurrence_type(timeline_obj)
                            if occur_type == thomasa88lib.timeline.OCCURRENCE_BODIES_COMP:
                                # Only the "Component from bodies" feature can be renamed
                                rename_objs.append(RenameInfo(label, timeline_obj, timeline_obj.entity))
                            
                                # In fact, it only makes sense to rename that timeline feature:
                                # * New empty component already has a name field and it is
                                #   forced onto the timeline object.
                                # * Copy component means that the component already has a name.
                                # Let the user name the component:
                                rename_objs.append(RenameInfo("Component", entity.component, entity.component))
                        else:
                            rename_objs.append(RenameInfo(label, timeline_obj, entity))
                            if hasattr(entity, 'bodies'):
                                for body in entity.bodies:
                                    if UNNAMED_BODY_PATTERN.match(body.name):
                                        rename_objs.append(RenameInfo(label + ' Body', body, body))
                    else:
                        # re: Move1 -> Move
                        label = re.sub(r'[0-9].*', '', timeline_obj.name)
                        rename_objs.append(RenameInfo(label, timeline_obj, None))

    last_flat_timeline_ = current_flat_timeline
    return rename_objs

def rename_command_created_handler(args: adsk.core.CommandCreatedEventArgs):
    # The nifty thing with cast is that code completion then knows the object type
    cmd = adsk.core.Command.cast(args.command)
    
    # Don't spam the right click shortcut menu
    cmd.isRepeatable = False
    # Don't save if the user goes on to another command
    cmd.isExecutedWhenPreEmpted = False

    events_manager_.add_handler(cmd.execute,
                                callback=rename_command_execute_handler)
    
    events_manager_.add_handler(cmd.executePreview,
                                callback=rename_command_execute_preview_handler)

    events_manager_.add_handler(cmd.destroy,
                                callback=rename_command_destroy_handler)
    
    events_manager_.add_handler(cmd.inputChanged,
                                callback=rename_command_input_changed_handler)

    inputs = cmd.commandInputs
    inputs.addTextBoxCommandInput('info', '', 'Press Tab to focus on the textbox.', 1, True)

    # Using a table, since it will trigger inputChanged when the user uses the mouse to focus
    # an input. Unfortunately, it does not trigger on focus change made by the keyboard.
    table = inputs.addTableCommandInput('table', '', 2, '2:3')
    table.tablePresentationStyle = adsk.core.TablePresentationStyles.transparentBackgroundTablePresentationStyle

    for i, rename in enumerate(rename_objs_):
        label_input = table.commandInputs.addStringValueInput(f'label_{i}', '', rename.label)
        label_input.isReadOnly = True
        if rename.rename_type == RenameType.API:
            obj_name = rename.name_obj.name
        elif rename.rename_type == RenameType.TEXT_COMMAND:
            obj_name = neu_server.get_user_name(rename.name_obj)
        else:
            raise Exception(f"Unknown rename type: {rename.rename_type}")
        string_input = table.commandInputs.addStringValueInput(f'string_{i}', rename.label, obj_name)
        table.addCommandInput(label_input, i, 0)
        table.addCommandInput(string_input, i, 1)

    cmd.okButtonText = 'Set name (Enter)'
    cmd.cancelButtonText = 'Skip (Esc)'

    if table.rowCount > 0:
        focus_changed(table.getInputAtPosition(0, 0))

def rename_command_execute_handler(args: adsk.core.CommandEventArgs):
    cmd = args.command
    inputs = cmd.commandInputs

    # No command is recorded to undo history as long as we don't do
    # anything during the execute.

    failures = try_rename_objects(inputs)

    if failures:
        # At least on operation failed
        args.executeFailed = True
        args.executeFailedMessage = f"{NAME} failed. Failed to rename features:<ul>"
        for old_name, new_name in failures:
            args.executeFailedMessage += f'<li>"{old_name}" -> "{new_name}"'
        args.executeFailedMessage += "</ul>"

def rename_command_execute_preview_handler(args: adsk.core.CommandEventArgs):
    failures = try_rename_objects(args.command.commandInputs)
    args.isValidResult = not failures

def rename_command_destroy_handler(args: adsk.core.CommandEventArgs):
    # Clear up automatic selections made during edit
    global prev_focused_input_
    if prev_focused_input_:
        ui_.activeSelections.clear()

    # Update state
    check_timeline(init=True)

def rename_command_input_changed_handler(args: adsk.core.InputChangedEventArgs):
    # Unfortunately, we cannot know when an input is selected using the keyboard,
    # so selecting an object on input change is the best we can do.
    focus_changed(args.input)

prev_focused_input_ = None
def focus_changed(input):
    global prev_focused_input_
    if input == prev_focused_input_:
        return
    prev_focused_input_ = input

    rename = rename_objs_[int(input.id.split('_')[-1])]

    ui_.activeSelections.clear()

    if rename.rename_type == RenameType.API:
        # Selection logic from VerticalTimeline
        design: adsk.fusion.Design = app_.activeProduct
        entity = rename.select_obj
        if not entity:
            # We did not manage to grab the entity we want to select
            return

        # Making this in a transactory way so the current selection is not removed
        # if the entity is not selectable.
        newSelection = adsk.core.ObjectCollection.create()

        if isinstance(entity, adsk.fusion.Occurrence):
            associated_component = entity.sourceComponent
        elif isinstance(entity, adsk.fusion.ConstructionPlane):
            associated_component = entity.parent
        elif hasattr(entity, 'parentComponent'):
            associated_component = entity.parentComponent
        else:
            print(f'DirectName: {thomasa88lib.utils.short_class(entity)} does not have parent component')
            return

        if associated_component == design.rootComponent:
            # There are no occurrences of root. Just a single instance: root. Can select the entity directly.
            newSelection.add(entity)
        else:
            #Using _all_OccurrencesByComponent to get nested occurrences.
            in_occurrences = design.rootComponent.allOccurrencesByComponent(associated_component)
            if hasattr(entity, 'createForAssemblyContext'):
                for occurrence in in_occurrences:
                    proxy = entity.createForAssemblyContext(occurrence)
                    newSelection.add(proxy)
            elif hasattr(entity, 'bodies'):
                # Workaround for Feature objects
                ### TODO: Correctly select Feature objects. E.g. BoxFeature, CylinderFeature, ...
                ###       so that editing them works.
                for body in entity.bodies:
                    for occurrence in in_occurrences:
                        proxy = body.createForAssemblyContext(occurrence)
                        newSelection.add(proxy)

        try:
            ui_.activeSelections.all = newSelection
        except RuntimeError as e:
            print(f'{NAME} failed to select {thomasa88lib.utils.short_class(entity)}: {e}')
    elif rename.rename_type == RenameType.TEXT_COMMAND:
        #neu_ui.add_selection(rename.name_obj) # Need "valid JSON" for this
        # Commands.Select seems to only accept an ONK (path)
        # Selections.Add seems to accept an ONK (path), an entity ID or entity ref (name)(?)
        app_.executeTextCommand(f'Selections.Add {rename.name_obj}')
        #app_.executeTextCommand(f'Commands.Select "ONK::*/*/VisualAnalyses/SectionViewAnalysis=0"')

def try_rename_objects(inputs):
    failures = []

    for i, rename in enumerate(rename_objs_):
        input = inputs.itemById(f'string_{i}')
        try:
            if rename.rename_type == RenameType.API:
                if rename.name_obj.name != input.value:
                    rename.name_obj.name = input.value
            elif rename.rename_type == RenameType.TEXT_COMMAND:
                if neu_server.get_user_name(rename.name_obj) != input.value:
                    neu_server.rename(rename.name_obj, input.value)
            else:
                raise Exception(f"Unknown rename type: {rename.rename_type}")
        except RuntimeError as e:
            failures.append((rename.name_obj.name, input.value))
            error_info = str(e)
            error_split = error_info.split(' : ', maxsplit=1)
            if len(error_split) == 2:
                error_info = error_split[1]
    
    return failures

def run(context):
    global app_
    global ui_
    global rename_cmd_def_
    with error_catcher_:
        app_ = adsk.core.Application.get()
        ui_ = app_.userInterface

        # Make sure an old version of this command is not running and blocking the "add"
        if ui_.activeCommand == SET_NAME_CMD_ID:
            ui_.terminateActiveCommand()

        old_cmd_def = ui_.commandDefinitions.itemById(SET_NAME_CMD_ID)
        if old_cmd_def:
            old_cmd_def.deleteMe()

        # Use a Command to get a transaction when renaming
        rename_cmd_def_ = ui_.commandDefinitions.addButtonDefinition(SET_NAME_CMD_ID,
                                                                    f'{NAME} (v {manifest_["version"]})',
                                                                    '',
                                                                    './resources/rename_icon')

        events_manager_.add_handler(rename_cmd_def_.commandCreated,
                                    callback=rename_command_created_handler)
        
        events_manager_.add_handler(ui_.workspaceActivated,
                                    callback=workspace_activated_handler)
        
        events_manager_.add_handler(ui_.workspacePreDeactivate,
                                    callback=workspace_pre_deactivate_handler)

        if app_.isStartupComplete and ui_.activeWorkspace.id == 'FusionSolidEnvironment':
            check_timeline(init=True)
            enable()

def stop(context):
    with error_catcher_:
        events_manager_.clean_up()

        cmd_def = ui_.commandDefinitions.itemById(SET_NAME_CMD_ID)
        if cmd_def:
            cmd_def.deleteMe()
