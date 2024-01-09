import json
# boto3 is provided by the lambda runtime environment
import boto3
# pymysql is loaded from the requirements.txt
import pymysql
from os import getenv
from datetime import datetime

from botocore.client import Config

config = Config(connect_timeout=5, retries={'max_attempts': 0})
s3 = boto3.client('s3', region_name="us-east-2", config=config)
secretsmanager = boto3.client('secretsmanager', region_name="us-east-2", config=config)

gemp_db_credentials_secret_id = "gempdb_stats"

rds_host = None
rds_username = None
rds_password = None
rds_dbname = None
rds_port = None
rds_engine = None

print("Retrieving Secret {} from SecretsManager".format(gemp_db_credentials_secret_id))
try:
  gemp_db_credentials_secret = secretsmanager.get_secret_value(SecretId=gemp_db_credentials_secret_id)
  gemp_db_credentials_secret_string = json.loads(gemp_db_credentials_secret["SecretString"])    
  print(gemp_db_credentials_secret_string)
  rds_host     = gemp_db_credentials_secret_string["host"]
  rds_username = gemp_db_credentials_secret_string["username"]
  rds_password = gemp_db_credentials_secret_string["password"]
  rds_dbname   = gemp_db_credentials_secret_string["dbname"]
  rds_port     = gemp_db_credentials_secret_string["port"]
  rds_engine   = gemp_db_credentials_secret_string["engine"]

except Exception as e:
  print("Failed to retrieve database credentials from Secrets Manager")
  print("Tried to pull {} and expected a map with value:".format(gemp_db_credentials_secret_id))
  print('{"username":"xxxx", "password":"xxxx", "dbname":"gemp-swccg"}')
  print(e)
  print("Trying to pull credentials from Environment Variables")
  rds_host = getenv("RDS_HOST", "localhost")
  rds_username = getenv("RDS_USERNAME", "gemp")
  rds_password = getenv("RDS_PASSWORD", "Four_mason8pirate")
  rds_dbname = getenv("RDS_DBNAME", "gemp-swccg")


s3_bucket_name = getenv("S3_BUCKET_NAME", "gemp-stats")


##
## Run query against MySQL and upload results to S3.
## Database connection is re-used across all queries,
##   so the connection is established outside of the ETL function.
##
def etl(conn, query, s3_file_name):
  print("..* {} Executing Query Against Database".format(datetime.now()))
  with conn.cursor() as cur:
    try:
      cur.execute(query)
      conn.commit()
    except Exception as e:
      print("..* {} Unable to query database".format(datetime.now()))
      print(e)
      # unable to query database, returning false
      return False

    print("..* {} Parsing Rows from Database")
    rows = []
    for row in cur:
      row = map(lambda x: x.isoformat() if isinstance(x, datetime) else x, row)
      rows.append(list(row))

    # Convert rows to JSON and write to the file
    print("..* {} Writing JSON file: {}".format(datetime.now(), s3_file_name))
    try:
      with open(f"/tmp/{s3_file_name}", 'w') as fh:
        json.dump({"rows": rows}, fh)
    except Exception as error:
      print("..* {} Unable to write query results to file: {}".format(datetime.now(), s3_file_name))
      print(error)
      # writing the file failed, return false
      return False

    # Upload JSON to s3
    print("..* {} Uploading file to S3: s3://{}/{}".format(datetime.now(), s3_bucket_name, s3_file_name))
    try:
      with open(f"/tmp/{s3_file_name}", 'rb') as fh:
        s3.upload_fileobj(fh, s3_bucket_name, s3_file_name)
        return True
    except Exception as e:
      print("..* {} Unable to upload file {} to S3 bucket: {}".format(datetime.now(), s3_file_name, s3_bucket_name))
      print(e)
      # upload to s3 failed, return false
      return False

    return False

##
## Lambda Handler
##
def lambda_handler(event, context):

  ##
  ## Setup connection to MySQL Database
  ##
  print("Connecting to MySQL Database")
  print("..*.RDS Host....: {}".format(rds_host))
  print("..*.RDS Database: {}".format(rds_dbname))
  print("..*.RDS Username: {}".format(rds_username))
  conn = None
  try:
    conn = pymysql.connect(host=rds_host, user=rds_username, passwd=rds_password, db=rds_dbname, connect_timeout=5)
  except Exception as e:
    print("Unable to connect to database")
    print(e)
    return(json.dumps({"status": "unable to connect to database"}))

  ##
  ## How far in to the past to go.
  ## Allows passing the date in the *since* variable in to the Lambda event.
  ## By default, use June 1, 2021.
  ##
  since_datetime = event.get("since", "2021-06-01 00:19")
  print("Queries will pull records since: {}".format(since_datetime))

  ##
  ## Deck Archetype Statistics
  ## takes 25 seconds to run
  ##
  deck_archetype_query = """
  SELECT format_name, tournament, winner, loser, win_reason, winner_deck_archetype, loser_deck_archetype, winner_side, enddatetime, id, timestampdiff(second,startdatetime,enddatetime) as GameDuration, sealed_league_type
    FROM deck_archetype_view_public
   WHERE enddatetime >= '%s' """ % (since_datetime,)

  ##
  ## Run the query and upload the results to S3 so it can be consumed by the GEMP website.
  ##
  time_a = datetime.now()
  print("{} Running the Deck Archectype Statistics Query".format(time_a))
  etl(conn, deck_archetype_query, "deck_archetype.json")
  time_b = datetime.now()
  print("{} Deck Archectype Statistics Query complete: {}".format(time_b, (time_b - time_a)))

  return {"statusCode": 200,"body": "OK"}

##
## For local testing, allow a way to call the handler as the main function
##
if __name__ == "__main__":
  try:
    from dotenv import load_dotenv
    load_dotenv()
  except Exception as e:
    print(e)

  params = {
    "since": "2021-06-01 00:19"
  }

  print(lambda_handler(params, ""))

