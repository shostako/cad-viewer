' cad-viewer launcher (Windows).
' Double-click to start the WSL backend (frontend bundled) and open the browser
' with NO console window. Idempotent: if it is already running, it just opens
' the browser. Edit the distro name below if yours differs (wsl.exe -l -q).
Set sh = CreateObject("WScript.Shell")
sh.Run "wsl.exe -d Ubuntu-24.04 bash -lc ""~/ClaudeCode/cad-viewer/start.sh""", 0, False
