
Add-Type -AssemblyName System.Windows.Forms

$result = [System.Windows.Forms.MessageBox]::Show(
    "Arda AI Agent baslatilsin mi?`n`n3 arama, 20 dakika arayla.",
    "Arda AI Agent",
    [System.Windows.Forms.MessageBoxButtons]::YesNo,
    [System.Windows.Forms.MessageBoxIcon]::Question
)

if ($result -eq [System.Windows.Forms.DialogResult]::Yes) {

    # Automatically detect the project directory
    $project = $PSScriptRoot

    # Start the agent using the project's Python virtual environment
    Start-Process -FilePath "powershell.exe" `
        -ArgumentList @(
            "-NoExit",
            "-Command",
            "Set-Location '$project'; & '.\.venv312\Scripts\python.exe' '.\main_agent.py'"
        ) `
        -WorkingDirectory $project
}
