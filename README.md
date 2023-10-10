# arcmanager_backend

This is the Backend for the arcmanager.
It runs with fastapi and uvicorn

Both need to be installed first:

```sh
pip install fastapi
```

```sh
pip install "uvicorn[standard]"
```

To run the server first activate your virtual environment

Then install the dependencies from requirements.txt with:

```sh
pip install -r requirements.txt
```

For development run:

```sh
uvicorn main:app --reload
```

For production run:

```sh
uvicorn main:app
```

To test the backend, browse to: [localhost](http://localhost:8000/docs)

Currently the backend connects mainly to [gitdev.nfdi4plants.org](https://gitdev.nfdi4plants.org/explore)

## Authentication flow in the backend

Storing access tokens unencrypted on the client side, as done at the moment is a security issue. Several articles recommend moving token retrieval and storage to the backend, where they can be securely stored as a better alternative.

Envisioned authentication flow:

1. User requests login in frontend and is redirected to /login endpoint of the backend. (separate endpoints for different gitlab implementations?)
2. Authentication request URL is constructed in the backend.
3. Authentication URL is returned to client and login credentials have to be entered.
4. /auth endpoint in the backend is called after succesfull login.
5. Backend retrieves access token.
6. Starlette session middleware is used to create user session and stores access token and other session info.
7. Backend returns session ID in (httponly) cookie to frontend/browser.
8. Frontend forwards session ID cookie when further calls are made to backend, which allows retrieval of correct access token from backend user session.
9. Access token is used to make (e.g. gitlab) API calls and response is returned to frontend.

Required libraries:

```python
from starlette.config import Config
from starlette.requests import Request
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import HTMLResponse, RedirectResponse
from authlib.integrations.starlette_client import OAuth, OAuthError
```

See [this repo](https://github.com/authlib/demo-oauth-client/blob/master/fastapi-google-login/app.py), [this doc page](https://docs.authlib.org/en/latest/client/fastapi.html), and [this stackoverflow post](https://stackoverflow.com/questions/72975593/where-to-store-tokens-secrets-with-fastapi-python) for example implementation.

First working implementation of backend session management is done. The browser should forward the session ID cookie with every API request, so that session information can be accessed in the backend. At least `from starlette.requests import Request` needs to be added to endpoint scripts to allow access to session object (needs to be tested).

## Production deployment

### VM access

Access to VM is only possible when public key is added to authorized_keys file of the VM. The VM is accessed through another server running HAProxy, thats why a specific port needs to be addressed.

```
ssh -i /path/to/keyfile -p 29101 ubuntu@193.196.20.50
```

### VM setup

Clone repository and install necessary software:

```bash
# clone repository from Git
git clone https://github.com/Lu98Be/arcmanager_backend.git

# check if correct python version is active
python3 --version
>Python 3.11.4

# create virtual environment "env"
python3 -m venv env

# activate virtual environment
source env/bin/activate

# upgrade pip
pip install --upgrade pip

# install required python packages stored in requirements.txt
pip install -r requirements.txt

# install additional packages to serve webapp
pip install gunicorn

# deactivate virtual env
deactivate
```

Create new socket file /etc/systemd/system/gunicorn.socket:

```bash
[Unit]
Description=gunicorn socket

[Socket]
ListenStream=/run/gunicorn.sock

[Install]
WantedBy=sockets.target
```

Create new service file /etc/systemd/system/gunicorn.service:

```bash
[Unit]
Description=gunicorn daemon
Requires=gunicorn.socket
After=network.target

[Service]
User=ubuntu
Group=www-data
## define additional environment parameters here:
Environment="SCRIPT_NAME=/arcmanager"

WorkingDirectory=/home/ubuntu/arcitect_web/arcmanager_backend
ExecStart=/home/ubuntu/arcitect_web/arcmanager_backend/env/bin/gunicorn \
          --access-logfile - \
          --workers 4 \
          --worker-class uvicorn.workers.UvicornWorker \
          --bind unix:/run/gunicorn.sock \
          main:app

[Install]
WantedBy=multi-user.target
```

Start and test socket:

```bash
# start and enable socket
sudo systemctl start gunicorn.socket
sudo systemctl enable gunicorn.socket

# check systemctl status page
sudo systemctl status gunicorn.socket

# see if socket file was created
file /run/gunicorn.sock

# if errors occur, check log
sudo journalctl -u gunicorn.socket

# send connection to socket (html output expected)
curl --unix-socket /run/gunicorn.sock http://localhost/arcmanager/api/v1/docs

# check status of backend service (should be active)
sudo systemctl status gunicorn

# when errors occur, check log
sudo journalctl -u gunicorn
```

---

RELOAD SERVICE TO APPLY CHANGES

- whenever changes are made to the gunicorn.service file, or to the fastapi application reload deamon and restart the service to apply changes:

```bash
sudo systemctl daemon-reload
sudo systemctl restart gunicorn
```

---

Create new nginx server block file /etc/nginx/sites-available/arcmanager:

```bash
server {
    listen 80;
    listen [::]:80;
    server_name nfdi4plants.de www.nfdi4plants.de;
    root /home/ubuntu/arcitect_web/arcmanager_backend;

    access_log /var/log/arcmanager_access.log;
    error_log /var/log/arcmanager_error.log;

    location /arcmanager/api {
        include proxy_params;
        proxy_pass http://gunicorn_sock;
    }
}

upstream gunicorn_sock {
        server unix:/run/gunicorn.sock;
}
```

Enable site and test for syntax errors:

```bash
# link configuration file to sites-enable directory
sudo ln -s /etc/nginx/sites-available/arcmanager /etc/nginx/sites-enabled/arcmanager

# test nginx configuration
sudo nginx -t

# restart nginx
sudo systemctl restart nginx
```

### Troubleshooting on the server side

Collection of useful commands and location of log and config files on the server:

#### Log files

| Description           | File path                                                                                 |
| --------------------- | ----------------------------------------------------------------------------------------- |
| access log            | /var/log/arcmanager_access.log                                                            |
| proxy error log       | /var/log/arcmanager_error.log                                                             |
| application error log | accessed via `sudo journalctl -u gunicorn` (use <kbd>End</kbd> to jump to recent entries) |

#### Config files

| Description                    | File path                             |
| ------------------------------ | ------------------------------------- |
| gunicorn service configuration | /etc/systemd/system/gunicorn.service  |
| gunicorn socket configuration  | /etc/systemd/system/gunicorn.socket   |
| Nginx proxy configuration      | /etc/nginx/sites-available/arcmanager |

#### Useful commands

```bash
# Restart gunicorn service and uvicorn workers to apply changes to the application code
sudo systemctl daemon-reload
sudo systemctl restart gunicorn

# restart nginx service to apply changes to the proxy config
sudo nginx -t
sudo systemctl restart nginx

# check status of gunicorn service and uvicorn workers
sudo systemctl status gunicorn

# check status of reverse proxy
sudo systemctl status nginx

# open logfiles of uvicorn workers (shows e.g. application errors)
sudo journalctl -u gunicorn

```
