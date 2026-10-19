-- Wiretrace.app: start a session without Terminal. scripts/make-app.sh compiles this on the
-- tester's Mac. The logic is in `wiretrace app` (cli/app.py); this only shows dialogs. It starts
-- the project and device `app state` names on its `next` line; the window switches either.
-- Specs: docs/specs/014-mac-app-install-and-launcher.md, 018-switch-device.md (extension A),
-- 019-app-hint-in-the-window.md.
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
	set projectName to ""
	set deviceName to ""
	repeat with stateLine in paragraphs of stateText
		set stateLine to stateLine as text
		if stateLine starts with "running " then
			set recordingPreset to text 9 thru -1 of stateLine
		else if stateLine starts with "next " then
			-- A project name has no space; the device label may.
			set nextText to text 6 thru -1 of stateLine
			set spaceAt to offset of " " in nextText
			if spaceAt > 1 and spaceAt < (length of nextText) then
				set projectName to text 1 thru (spaceAt - 1) of nextText
				set deviceName to text (spaceAt + 1) thru -1 of nextText
			end if
		end if
	end repeat

	if recordingPreset is not "" then
		display dialog "Wiretrace is already recording " & recordingPreset & ". Use the Wiretrace menu (the W icon at the top right) to open the window or stop." with title appTitle buttons {"OK"} default button "OK"
		return
	end if
	if projectName is "" then
		set answer to display dialog "No project yet. Add one to the presets folder (user guide, Part 2), then open Wiretrace again." with title appTitle buttons {"Open presets folder", "OK"} default button "OK"
		if button returned of answer is "Open presets folder" then
			do shell script "open " & quoted form of (root & "/presets")
		end if
		return
	end if

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
	-- Once started, the window shows where to switch and how to stop: no dialog.
	if startOutput is "starting" then
		display dialog "Wiretrace is still starting " & projectName & " on " & deviceName & ". The window opens when it is ready." with title appTitle buttons {"OK"} default button "OK" giving up after 15
	end if
end run

on showError(message)
	display dialog message with title appTitle buttons {"OK"} default button "OK" with icon stop
end showError
