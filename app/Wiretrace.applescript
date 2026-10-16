-- Wiretrace.app: start a session without Terminal. scripts/make-app.sh compiles this on the
-- tester's Mac. The logic is in `wiretrace app` (cli/app.py); this only shows lists and dialogs.
-- Spec: docs/specs/014-mac-app-install-and-launcher.md.
--
-- ASCII only: the ellipsis is made with `character id`.

property appTitle : "Wiretrace"

on run
	set ellipsis to character id 8230
	set rootFile to (POSIX path of (path to me)) & "Contents/Resources/wiretrace-root"
	try
		set root to do shell script "head -n 1 " & quoted form of rootFile
	on error
		showError("Wiretrace.app is incomplete. In Terminal, run scripts/setup-mac.sh in the Wiretrace folder.")
		return
	end try
	set cli to root & "/wiretrace"
	try
		do shell script "test -x " & quoted form of cli
	on error
		showError("Wiretrace is not in " & root & " any more. In Terminal, run scripts/setup-mac.sh from its new folder.")
		return
	end try

	try
		set stateText to do shell script quoted form of cli & " app state"
	on error errText
		showError(errText)
		return
	end try
	set recordingPreset to ""
	set projectNames to {}
	set deviceNames to {}
	set lastProject to ""
	set lastDevice to ""
	repeat with stateLine in paragraphs of stateText
		set stateLine to stateLine as text
		if stateLine starts with "running " then
			set recordingPreset to text 9 thru -1 of stateLine
		else if stateLine starts with "project " then
			set end of projectNames to text 9 thru -1 of stateLine
		else if stateLine starts with "device " then
			set end of deviceNames to text 8 thru -1 of stateLine
		else if stateLine starts with "last " then
			set lastText to text 6 thru -1 of stateLine
			set spaceAt to offset of " " in lastText
			if spaceAt > 1 and spaceAt < (length of lastText) then
				set lastProject to text 1 thru (spaceAt - 1) of lastText
				set lastDevice to text (spaceAt + 1) thru -1 of lastText
			end if
		end if
	end repeat

	if recordingPreset is not "" then
		display dialog "Wiretrace is already recording " & recordingPreset & ". Use the Wiretrace menu (the W at the top right) to open the window or stop." with title appTitle buttons {"OK"} default button "OK"
		return
	end if
	if projectNames is {} then
		set answer to display dialog "No project yet. Add one to the presets folder (user guide, Part 2), then open Wiretrace again." with title appTitle buttons {"Open presets folder", "OK"} default button "OK"
		if button returned of answer is "Open presets folder" then
			do shell script "open " & quoted form of (root & "/presets")
		end if
		return
	end if

	set projectDefault to item 1 of projectNames
	if projectNames contains lastProject then set projectDefault to lastProject
	set picked to choose from list projectNames with title appTitle with prompt "Project:" default items {projectDefault} OK button name "Next" cancel button name "Quit"
	if picked is false then return
	set projectName to item 1 of picked

	set deviceDefault to item 1 of deviceNames
	if deviceNames contains lastDevice then set deviceDefault to lastDevice
	set picked to choose from list deviceNames with title appTitle with prompt "Device:" default items {deviceDefault} OK button name "Start" cancel button name "Quit"
	if picked is false then return
	set deviceName to item 1 of picked

	set progress total steps to -1
	set progress completed steps to 0
	set progress description to "Starting Wiretrace" & ellipsis
	set progress additional description to projectName & ", " & deviceName
	try
		set startOutput to do shell script quoted form of cli & " app start --project " & quoted form of projectName & " --device " & quoted form of deviceName
	on error errText
		showError(errText)
		return
	end try
	if startOutput is "starting" then
		set message to "Wiretrace is still starting " & projectName & ". The window opens when it is ready."
	else
		set message to "Wiretrace is recording " & projectName & "."
	end if
	display dialog message & " Stop it from the Wiretrace menu (the W at the top right)." with title appTitle buttons {"OK"} default button "OK" giving up after 15
end run

on showError(message)
	display dialog message with title appTitle buttons {"OK"} default button "OK" with icon stop
end showError
