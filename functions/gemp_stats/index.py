import json
import boto3
from os import getenv

def lambda_handler(event, context):

  conn = None
  try:
    conn = pymysql.connect(rds_host, user=rds_username, passwd=rds_password, db=db_name, connect_timeout=5)
  except Exception as e:
    print("Unable to connect to databse")

  with conn.cursor() as cur:
    cur.execute("SELECT COUNT(*) FROM game_history")
    conn.commit()

  return {
    "statusCode": 200,
    "body": "ok"
  }
