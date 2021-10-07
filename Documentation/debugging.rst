Debugging
=========

How to configure IDE Visual Code Studio to open project with properly configured Python debugger.

Needed extensions
-----------------
- Docker (`ext install ms-azuretools.vscode-docker`)
- Python (`ext install ms-python.python`)
- Remote Containers (`ext install ms-vscode-remote.remote-containers`)


Method 1: Python: Remote Attach
-------------------------------
Using debugpy server from the inside of docker container.

1. Configure your `.vscode/launch.json` -- see `.vscode.example`


Method 2: Attach to Running Container
-------------------------------------
