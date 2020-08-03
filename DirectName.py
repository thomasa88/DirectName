#Author-Thomas Axelsson
#Description-Shows a naming dialog directly after creating a feature.

# This file is part of DirectName, a Fusion 360 add-in for naming
# features directly after creation.
#
# Copyright (C) 2020  Thomas Axelsson
#
# DirectName is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# DirectName is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with DirectName.  If not, see <https://www.gnu.org/licenses/>.

import adsk.core, adsk.fusion, adsk.cam, traceback

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

SET_NAME_CMD_ID = 'thomasa88_setFeatureName'
AFTER_COMMAND_TERMINATE_ID = 'thomasa88_instantNameAfterCommandTerminate'

app_ = None
ui_ = None

error_catcher_ = thomasa88lib.error.ErrorCatcher(msgbox_in_debug=False)
events_manager_ = thomasa88lib.events.EventsManager(error_catcher_)
manifest_ = thomasa88lib.manifest.read()

need_init_ = True
last_flat_timeline_ = None
rename_cmd_def_ = None
rename_objs_ = None

def workspace_activated_handler(args):
    #eventArgs = adsk.core.WorkspaceEventArgs.cast(args)

    # DocumentActivated is not always triggered (2020-07-27), so we mark
    # that we need an update here, but it will actually trigger on the
    # first command. (The timeline is not ready on in this event.)
    # Bug: # Bug: https://forums.autodesk.com/t5/fusion-360-api-and-scripts/api-bug-application-documentactivated-event-do-not-raise/m-p/9020750

    global need_init_
    need_init_ = True
    print("NEED INIT")

def command_terminated_handler(args):
    if ui_.activeWorkspace.id != 'FusionSolidEnvironment':
        # Only for the Design workspace
        return

    eventArgs = adsk.core.ApplicationCommandEventArgs.cast(args)
    
    #print("TERM", eventArgs.commandId, eventArgs.terminationReason, app_.activeEditObject.classType())

    global need_init_
    if need_init_:
        check_timeline(init=True)
        need_init_ = False
        return

    if eventArgs.terminationReason != adsk.core.CommandTerminationReason.CompletedTerminationReason:
        return

    # Heavy traffic commands
    if eventArgs.commandId in ['SelectCommand', 'CommitCommand']:
        return

    if eventArgs.commandId == SET_NAME_CMD_ID:
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
    # Therefore, lets use an event to put ourselves at the end of the event queue.
    app_.fireCustomEvent(AFTER_COMMAND_TERMINATE_ID)

def after_terminate_handler(args):
    global need_init_
    if not ui_.activeCommand or ui_.activeCommand == 'SelectCommand':
        check_timeline()

def check_timeline(init=False):
    global last_flat_timeline_
    print("CHECK", not init)
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
                global rename_objs_

                rename_objs_ = []
                for timeline_obj in new_objs:
                    # Can't access entity of all timeline objects
                    # Bug: https://forums.autodesk.com/t5/fusion-360-api-and-scripts/api-bug-cannot-access-entity-of-quot-move-quot-feature/m-p/9651921
                    try:
                        entity = timeline_obj.entity
                    except RuntimeError:
                        entity = None
                    if entity:
                        label = thomasa88lib.utils.short_class(timeline_obj.entity).replace('Feature', '')
                        comp_type = thomasa88lib.timeline.get_occurrence_type(timeline_obj)
                        if comp_type != thomasa88lib.timeline.OCCURRENCE_NOT_OCCURRENCE:                      
                            if comp_type == thomasa88lib.timeline.OCCURRENCE_BODIES_COMP:
                                # Only the "Component from bodies" feature can be renamed
                                rename_objs_.append((timeline_obj, timeline_obj, label))
                            
                                # In fact, it only makes sense to rename that timeline feature:
                                # * New empty component already has a name field and it is
                                #   forced onto the timeline object.
                                # * Copy component means that the component already has a name.
                                # Let the user name the component:
                                rename_objs_.append((timeline_obj, entity.component, "Component"))
                        else:
                            rename_objs_.append((timeline_obj, timeline_obj, label))
                    else:
                        # re: Move1 -> Move
                        label = re.sub(r'[0-9].*', '', timeline_obj.name)
                        rename_objs_.append((timeline_obj, timeline_obj, label))

                if rename_objs_:
                    rename_cmd_def_.execute()
    
    last_flat_timeline_ = current_flat_timeline

def rename_command_created_handler(args):
    eventArgs = adsk.core.CommandCreatedEventArgs.cast(args)

    # The nifty thing with cast is that code completion then knows the object type
    cmd = adsk.core.Command.cast(args.command)
    
    # Don't spam the right click shortcut menu
    cmd.isRepeatable = False
    # Don't save if the user goes on to another command
    cmd.isExecutedWhenPreEmpted = False

    events_manager_.add_handler(cmd.execute,
                                adsk.core.CommandEventHandler,
                                rename_command_execute_handler)
    
    events_manager_.add_handler(cmd.executePreview,
                                adsk.core.CommandEventHandler,
                                rename_command_execute_preview_handler)

    events_manager_.add_handler(cmd.destroy,
                                adsk.core.CommandEventHandler,
                                rename_command_destroy_handler)
    
    events_manager_.add_handler(cmd.validateInputs,
                                adsk.core.ValidateInputsEventHandler,
                                rename_command_validate_inputs_handler)

    inputs = cmd.commandInputs
    inputs.addTextBoxCommandInput('info', '', 'Press Tab to focus on the textbox.', 1, True)
    for i, (timeline_obj, name_obj, label) in enumerate(rename_objs_):
        inputs.addStringValueInput(str(i), label, name_obj.name)

    cmd.okButtonText = 'Rename (Enter)'
    cmd.cancelButtonText = 'Skip (Esc)'

def rename_command_execute_handler(args):
    eventArgs = adsk.core.CommandEventArgs.cast(args)
    cmd = eventArgs.command
    inputs = cmd.commandInputs

    # No command is recorded to undo history as long as we don't do
    # anything during the execute.

    failures, rename_count = try_rename_objects(inputs)

    if failures:
        # At least on operation failed
        eventArgs.executeFailed = True
        eventArgs.executeFailedMessage = f"{NAME} failed. Failed to rename features:<ul>"
        for old_name, new_name in failures:
            eventArgs.executeFailedMessage += f'<li>"{old_name}" -> "{new_name}"'
        eventArgs.executeFailedMessage += "</ul>"

def rename_command_execute_preview_handler(args):
    eventArgs = adsk.core.CommandEventArgs.cast(args)

    failures = try_rename_objects(eventArgs.command.commandInputs)
    eventArgs.isValidResult = not failures

def rename_command_destroy_handler(args):
    eventArgs = adsk.core.CommandEventArgs.cast(args)

    # Update state
    check_timeline(init=True)    

def rename_command_validate_inputs_handler(args):
    eventArgs = adsk.core.ValidateInputsEventArgs.cast(args)

    # Want to do rename_objects as a test in execute preview, but
    # Fusion stops calling the preview as soon as we set the state
    # to "invalid". Idea: Unset invalid if user changes an input.
    for input in eventArgs.inputs:
        if not input.isReadOnly and len(input.value) == 0:
            #eventArgs.areInputsValid = False
            break
    else:
        eventArgs.areInputsValid = True

def try_rename_objects(inputs):
    failures = []
    rename_count = 0

    for i, (timeline_obj, name_obj, label) in enumerate(rename_objs_):
        input = inputs.itemById(str(i))
        try:
            if name_obj.name != input.value:
                name_obj.name = input.value
                rename_count += 1
        except RuntimeError as e:
            failures.append((name_obj.name, input.value))
            error_info = str(e)
            error_split = error_info.split(' : ', maxsplit=1)
            if len(error_split) == 2:
                error_info = error_split[1]
    
    return failures, rename_count

def run(context):
    print("RUN")
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
                                                                    f'{NAME} v {manifest_["version"]}',
                                                                    '',
                                                                    './resources/rename_icon')

        events_manager_.add_handler(rename_cmd_def_.commandCreated,
                                    adsk.core.CommandCreatedEventHandler,
                                    rename_command_created_handler)
        
        events_manager_.add_handler(ui_.commandTerminated,
                                    adsk.core.ApplicationCommandEventHandler,
                                    command_terminated_handler)
        
        after_terminate_event = events_manager_.register_event(AFTER_COMMAND_TERMINATE_ID)
        events_manager_.add_handler(after_terminate_event,
                                    adsk.core.CustomEventHandler,
                                    after_terminate_handler)
        
        events_manager_.add_handler(ui_.workspaceActivated,
                                    adsk.core.WorkspaceEventHandler,
                                    workspace_activated_handler)

        check_timeline(init=True)

def stop(context):
    print("STOP")
    with error_catcher_:
        events_manager_.clean_up()

        cmd_def = ui_.commandDefinitions.itemById(SET_NAME_CMD_ID)
        if cmd_def:
            cmd_def.deleteMe()
