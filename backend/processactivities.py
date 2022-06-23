from datetime import timedelta
import json
import logging

def process_activities(client):

    already_parsed_activities = dict()
    # try:
        # already_parsed_activities_file = open("activities.json")
        # already_parsed_activities = json.load(already_parsed_activities_file)
    # except:
        # pass

    commuting_threshold = timedelta(minutes=45)
    activities = client.get_activities(after="2022-06-01")
    nb_rides_edited = 0
    nb_workout_edited = 0
    nb_activity = 0
    ride_kms = 0
    for activity in activities:
        if str(activity.id) in already_parsed_activities.keys():
            continue
        already_parsed_activities[str(activity.id)] = True
        nb_activity += 1
        try:
            logging.info (activity.type, activity.name, activity.start_date, activity.elapsed_time, activity.private)
        except:
            logging.info (activity.type, activity.name, activity.start_date, activity.elapsed_time, activity.private)
            
        if (activity.type == 'Ride') and activity.elapsed_time < commuting_threshold:
            if not activity.commute:
                logging.info("     One short ride set to commute")
                client.update_activity(activity_id=activity.id, commute=True)
            logging.info("     One short ride set to private EBike")
            nb_rides_edited += 1
            activity = client.update_activity(activity_id=activity.id, activity_type="EBikeRide", private=True)
        if activity.type == "Workout":
            if not activity.private:
                logging.info("     One public workout set to private")
                client.update_activity(activity_id=activity.id, private=True, name = "Yoga", activity_type = "Yoga")
                logging.info("     One workout set to yoga")
                nb_workout_edited += 1
            else:
                client.update_activity(activity_id=activity.id, name = "Yoga", activity_type = "Yoga")
                logging.info("     One workout set to yoga")
                nb_workout_edited += 1
            
        if activity.type == "Yoga":
            if not activity.private:
                logging.info("     One public yoga workout set to private")
                updated_activity = client.update_activity(activity_id=activity.id, private=True, name = "Yoga")
                nb_workout_edited += 1
        if activity.type == "EBikeRide":
            if not activity.private:
                logging.info("     One public e-bike ride set to private")
                client.update_activity(activity_id=activity.id, private=True)
                nb_rides_edited += 1
        if activity.type == 'Ride':
            if activity.start_date_local.year < 2021:
                continue
            ride_kms = ride_kms + activity.distance.num

    with open("activities.json", "w") as already_parsed_activities_file:
        json.dump(already_parsed_activities, already_parsed_activities_file)    
            
    logging.info("#rides > 01-01-2021 kms: ", ride_kms)
    logging.info("#rides edited: ", nb_rides_edited)
    logging.info( "#workout edited: ", nb_workout_edited)
    logging.info("#activities: ", nb_activity)

