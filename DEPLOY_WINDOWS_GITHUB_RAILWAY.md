# Deploy V3.10.4 from PowerShell to the existing GitHub/Railway project

Repository:
`https://github.com/vitya55519-alt/anb.git`

Local deploy folder:
`C:\Users\Woterson\Desktop\AnnaBot_deploy`

The V3.10.4 ZIP is flat: after extraction `main.py` is directly inside the extracted folder.

```powershell
$zip = "$env:USERPROFILE\Downloads\AnnaBot_V3_10_4_Visual_Identity_Engine_Railway_Ready.zip"
$src = "$env:USERPROFILE\Desktop\AnnaBot_V3_10_4_Visual_Identity_Engine_Railway_Ready"
$dst = "$env:USERPROFILE\Desktop\AnnaBot_deploy"

Remove-Item $src -Recurse -Force -ErrorAction SilentlyContinue
Expand-Archive -Path $zip -DestinationPath $src -Force

# Must exist before copying
Get-Item "$src\main.py"
Get-Item "$src\requirements.txt"

robocopy $src $dst /MIR /XD .git .venv __pycache__ /XF .env

Set-Location $dst
Get-Item .\main.py
Get-Item .\requirements.txt
git status
git add -A
git commit -m "Deploy AnnaBot V3.10.4 visual identity engine"
git push origin main
```

Railway start command:

```text
python main.py
```

Keep one bot replica when using Telegram long polling.


## V3.12 Gemini dialogue and optional Veo video

After deploying the ZIP, add `GEMINI_API_KEY` and the Gemini routing variables in Railway → service → Variables. Do not put the key into PowerShell history or Git. V3.19.4 removed Gemini/Veo video: video runs on Replicate, so also add `REPLICATE_API_TOKEN` in Railway Variables.
