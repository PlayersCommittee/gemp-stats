import json
import boto3
import pymysql
import os
from datetime import datetime

# TODO: Load these from AWS Secrets Manager in production
rds_host = None
rds_username = None
rds_password = None
db_name = None
s3_bucket_name = None

s3 = boto3.client('s3')

def etl(conn, query, s3_file_name):
  with conn.cursor() as cur:
    cur.execute(query)
    conn.commit()

    rows = []
    for row in cur:
      row = map(lambda x: x.isoformat() if isinstance(x, datetime) else x, row)
      rows.append(list(row))

    # Convert rows to JSON and write to the file
    try:
      with open(s3_file_name, 'w') as outfile:
        json.dump({"rows": rows}, outfile)
    except Exception as error:
      print(error)

    # Upload JSON to s3
    try:
      with open(s3_file_name, 'rb') as data:
        s3.upload_fileobj(data, s3_bucket_name, s3_file_name)
    except Exception as e:
      print(e)

    return True

def handler(event, context):
  conn = None
  try:
    conn = pymysql.connect(host=rds_host, user=rds_username, passwd=rds_password, db=db_name, connect_timeout=5)
  except Exception as e:
    print("unable to connect to database")
    print(e)
    return(json.dumps({"status": "unable to connect to database"}))

  since_datetime = event["since"]

  stats_query = """
  select format_name, tournament, winner, loser, win_reason, winner_deck_archetype, loser_deck_archetype, winner_side, enddatetime, id, timestampdiff(second,startdatetime,enddatetime) as GameDuration, sealed_league_type
  from deck_archetype_view_public
  where enddatetime >= '%s' """ % (since_datetime,)

  etl(conn, stats_query, f"gemp-stats-{since_datetime.split(' ')[0]}.json")

  return {
    "statusCode": 200,
    "body": "OK"
  }

if __name__ == "__main__":
  from dotenv import load_dotenv
  load_dotenv()

  rds_host = os.getenv("RDS_HOST")
  rds_username = os.getenv("RDS_USERNAME")
  rds_password = os.getenv("RDS_PASSWORD")
  db_name = os.getenv("DB_NAME")
  s3_bucket_name = os.getenv("S3_BUCKET_NAME")

  params = {
    "since": "2021-06-01 00:19"
  }

  print(handler(params, ""))
