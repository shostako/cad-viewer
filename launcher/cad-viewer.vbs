' cad-viewer launcher (Windows).
' Double-click to start the WSL backend (frontend bundled) and open the browser
' with NO console window. Idempotent: if it is already running, it just opens
' the browser. Runs in the DEFAULT WSL distro (the one marked * in wsl.exe -l -v),
' so the same file works on PCs whose distro names differ (Ubuntu-22.04 / 24.04).
' wsl.exe is called by full path: a bare "wsl.exe" fails with error 70
' (permission denied) from wscript on some PCs.
' Keep this file ASCII-only with CRLF line endings (wscript reads it as CP932).
Set sh = CreateObject("WScript.Shell")
sh.Run "%SystemRoot%\System32\wsl.exe bash -lc ""~/ClaudeCode/cad-viewer/start.sh""", 0, False
