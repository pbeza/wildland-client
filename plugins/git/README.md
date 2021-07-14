# Git plugin

This is a plugin that allows to expose git repositories as wildland containers with read-only access. 

### Creating the container

Creating a container for your repository is no different than creating containers for any of the other backends. It can be done by using the following command:

```
wl container create MYCONTAINER --path /git
```

Because of the `--path` parameter, your container will be visible under the `/wildland/git` directory. 

### Creating Git storage

To create the storage, use the following command:

```
wl storage create git --container MYCONTAINER \
                        --url URL_TO_REPO \
                        [--clone-location /PATH/TO/CLONE] \
                        [--username <username>] \
                        [--password <password>]
```
`--url` parameter specifies the url to the git repository you wish to clone and should be following the `http[s]://host.xz[:port]/path/to/repo.git` syntax.
`--clone-location` parameter specifies the location of the repo's clone. The cloning is done automatically by the backend. If you chose to use it's default value (`/tmp/git_repo`), it can be ommited. On the other hand, if you'd like the clone of the repository to be stored somewhere else, you can provide that location to the backend now.
`--username` optional parameter specifies the username and will be needed whenever you attempt to clone a private repository. If you choose to provide it (along with the password/token parameter), the default authorization with a prompt will be skipped. 
`--password` parameter specifies the password/token you choose to use for authorization purposes. 
You can find out how to create your own personal token for [GitLab][1] or [GitHub][2] here.

### Mounting

To mount the container you created, use the following command:

```
wl container mount MYCONTAINER
```

### GitPython documentation:

This plugin uses the GitPython module. More information about the module can be found here:
[https://gitpython.readthedocs.io/en/stable/][3]

[1]: https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html#create-a-personal-access-token
[2]: https://docs.github.com/en/github/authenticating-to-github/keeping-your-account-and-data-secure/creating-a-personal-access-token
[3]: https://gitpython.readthedocs.io/en/stable/
