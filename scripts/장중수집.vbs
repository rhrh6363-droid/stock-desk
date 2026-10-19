' 창 없이 장중수집.bat 를 실행한다 (작업 스케줄러용). 이 파일과 같은 이름의 .bat 를 부른다.
Dim sh, fso, bat
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
bat = Replace(WScript.ScriptFullName, ".vbs", ".bat")
sh.Run "cmd.exe /c """ & bat & """", 0, True
