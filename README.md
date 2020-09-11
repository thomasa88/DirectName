# ![](resources/rename_icon/32x32.png)DirectName

DirectName is an Autodesk® Fusion 360™ add-in for naming features and bodies directly after creation. After creating a feature (e.g. *Extrude*) a dialog prompts for names for the feature and any created bodies.

![Screenshot](screenshot.png)

## Installation
Download the add-in from the [Releases](https://github.com/thomasa88/DirectName/releases) page.

Unpack it into `API\AddIns` (see [How to install an add-in or script in Fusion 360](https://knowledge.autodesk.com/support/fusion-360/troubleshooting/caas/sfdcarticles/sfdcarticles/How-to-install-an-ADD-IN-and-Script-in-Fusion-360.html)).

Make sure the directory is named `DirectName`, with no suffix.

## Usage

A naming dialog will be shown automatically when new features are created.

Press Tab to navigate the inputs and press Enter when done. Press Esc to skip naming.

The object which name is being edited will be highlighted (Object does not get highlighted before an edit is made, due to Fusion 360™ API limitations.)

Enable/disable the naming dialog by clicking on the *DIRECTNAME* button under the *TOOLS* tab.

The add-in can be temporarily disabled using the *Scripts and Add-ins* dialog. Press *Shift+S* in Fusion 360™ and go to the *Add-Ins* tab.

## Known Limitations

* Highlighting of objects are delayed until the name is edited, if navigating with the keyboard.
* Does not work in Direct Edit mode.

## Author

This add-in is created by Thomas Axelsson.

## License

This project is licensed under the terms of the MIT license. See [LICENSE](LICENSE).

## Changelog

* v 1.2.0
  * Enable/Disable button. Autodesk® store conformance.
* v 1.1.3
  * Enable *Run on Startup* by default.
* v 1.1.2
  * Highlight correct entity on mouse focus (Focusing by keyboard still only happens after text change ([Limitation](https://forums.autodesk.com/t5/fusion-360-api-and-scripts/event-when-commandinput-is-focused/m-p/9693906)).)
  * Name Section Analyses after creation.
  * Fix error when closing documents and exiting Fusion 360™.
* v 1.1.1
  * Handle objects that are not selectable, due to Fusion 360™ [API limitations](https://forums.autodesk.com/t5/fusion-360-api-and-scripts/api-bug-cannot-access-entity-of-quot-move-quot-feature/m-p/9651921).
* v 1.1.0
  * Fix highlighting of bodies that are part of components.
* v 1.0.1
  * Pen logo
  * Autodesk® store conformance.
* v 1.0.0
  * New logo
* v 0.2.0
  * Rename new bodies and surfaces
  * Highlight active entity when name is edited
* v 0.1.3
  * Change to MIT license, for app store compatibility