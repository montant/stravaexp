#!flask/bin/python
import logging

from flask import Flask, render_template, redirect, url_for, request, jsonify
from stravalib import Client
import logging
import processactivities
import json
import os
import time

logging.basicConfig(level=logging.INFO)
stravalib_logger = logging.getLogger("stravalib.model.activity")
stravalib_logger.setLevel(logging.ERROR)

app = Flask(__name__)
app.config.from_envvar('APP_SETTINGS')

@app.route("/")
def login():
    client = Client()
    if os.path.exists("stravaexp.dat"):
        with open("stravaexp.dat", mode="r") as data_file:
            access_token = json.load(data_file)
        if time.time() > access_token['expires_at']:
            print('Token has expired, will refresh')
            refresh_response = client.refresh_access_token(
                client_id=app.config['STRAVA_CLIENT_ID'], 
                client_secret=app.config['STRAVA_CLIENT_SECRET'], 
                refresh_token=access_token['refresh_token'])
            access_token = refresh_response
            with open('stravaexp.dat', 'w') as f:
                json.dump(refresh_response, f)
            print('Refreshed token saved to file')
            client.access_token = refresh_response['access_token']
            client.refresh_token = refresh_response['refresh_token']
            client.token_expires_at = refresh_response['expires_at']
        else:
            print('Token still valid, expires at {}'
                .format(time.strftime("%a, %d %b %Y %H:%M:%S %Z", time.localtime(access_token['expires_at']))))
            client.access_token = access_token['access_token']
            client.refresh_token = access_token['refresh_token']
            client.token_expires_at = access_token['expires_at']

        strava_athlete = client.get_athlete()
        processed = processactivities.process_activities(client)

        return render_template(
            'login_results.html',
            athlete=strava_athlete,
            access_token=access_token,
            processed=processed)
    else:                
        url = client.authorization_url(client_id=app.config['STRAVA_CLIENT_ID'],
                                redirect_uri=url_for('.logged_in',
                                _external=True),
                                approval_prompt='auto',
                                scope=['read_all','activity:read_all','activity:write'])
        return render_template('login.html', authorize_url=url)


@app.route("/strava-oauth")
def logged_in():
    """
    Method called by Strava (redirect) that includes parameters.
    - state
    - code
    - error
    """
    error = request.args.get('error')
    state = request.args.get('state')
    if error:
        return render_template('login_error.html', error=error)
    else:
        code = request.args.get('code')
        client = Client()
        
        access_token = client.exchange_code_for_token(client_id=app.config['STRAVA_CLIENT_ID'],
                                                    client_secret=app.config['STRAVA_CLIENT_SECRET'],
                                                    code=code)
        with open('stravaexp.dat', 'w') as f:
            json.dump(access_token, f)
        
        strava_athlete = client.get_athlete()
        processed = processactivities.process_activities(client)

        return render_template(
            'login_results.html',
            athlete=strava_athlete,
            access_token=access_token,
            processed=processed)

    
if __name__ == '__main__':
    app.run(debug=True)