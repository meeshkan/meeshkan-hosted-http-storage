import json
from json.decoder import JSONDecodeError
from string import Template
from uuid import UUID

import jsonschema
import requests
from flask import Flask, request

import psycopg2
from meeshkan_hosted_authenticate import verify_token
from meeshkan_hosted_db import connect_to_db


def read_schema():
    with open("http-types-schema.json") as schema_file:
        content = schema_file.read()
        return json.loads(content)


def is_valid_uuid(uuid_candidate):
    try:
        UUID(uuid_candidate)
        return True
    except ValueError:
        return False


class InvalidFormatException(Exception):
    def __init__(self, message):
        self.message = message


app = Flask(__name__)
HTTP_TYPES_SCHEMA = read_schema()
INDEX_HTML = open("index.html").read()
CLAIM_HTML_TEMPLATE = Template(open("claim.html").read())


@app.route("/http-storage")
def get():
    return INDEX_HTML


@app.route("/http-storage/hosts", methods=["POST"])
def hosts():
    posted_body = json.loads(request.stream.read())
    access_token = posted_body["access_token"]
    verified_user = verify_token(access_token)
    user_id = verified_user["uid"]
    with connect_to_db() as db, db.cursor() as cursor:
        cursor.execute(
            """SELECT json_data->'request'->'host', COUNT(*)
                FROM http_data JOIN http_claimed_uuid USING (claim_uuid) WHERE user_id = %s GROUP BY 1""",
            (user_id,),
        )
        result = {}
        for row in cursor:
            result[row[0]] = row[1]
        return result


@app.route("/http-storage/download")
def download():
    host = request.args["host"]
    access_token = request.args["access_token"]
    verified_user = verify_token(access_token)
    user_id = verified_user["uid"]
    # TODO: Stream back response
    result = ""
    with connect_to_db() as db, db.cursor() as cursor:
        cursor.execute(
            """SELECT json_data #>> '{}'
                FROM http_data JOIN http_claimed_uuid USING (claim_uuid) WHERE user_id = %s AND json_data->'request'->>'host' = %s""",
            (user_id, host),
        )
        for row in cursor:
            result += row[0] + "\n"
    return (
        result,
        200,
        {
            "content-type": "application/x-ndjson",
            "content-disposition": 'attachment; filename="traffic-' + host + '.jsonl"',
        },
    )


@app.route("/http-storage/generate-schema")
def generate_schema():
    host = request.args["host"]
    access_token = request.args["access_token"]
    verified_user = verify_token(access_token)
    user_id = verified_user["uid"]
    traffic_log = ""
    with connect_to_db() as db, db.cursor() as cursor:
        cursor.execute(
            """SELECT json_data #>> '{}'
                FROM http_data JOIN http_claimed_uuid USING (claim_uuid) WHERE user_id = %s AND json_data->'request'->>'host' = %s""",
            (user_id, host),
        )
        for row in cursor:
            traffic_log += row[0] + "\n"
    response = requests.post(
        "https://meeshkan.io/schema-builder",
        data=traffic_log,
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    return (
        response.text,
        response.status_code,
        {
            "content-type": response.headers["content-type"],
            "content-disposition": response.headers["content-disposition"],
        },
    )


@app.route("/http-storage/<path:uuid>")
def claim_uuid_form(uuid):
    if not is_valid_uuid(uuid):
        return (
            f"Not a uuid: {uuid}. POST to /http-storage/$UUID",
            400,
            {"content-type": "text/plain"},
        )
    return CLAIM_HTML_TEMPLATE.substitute({"stored_uuid": uuid})


@app.route("/http-storage/claim", methods=["POST"])
def claim():
    posted_body = json.loads(request.stream.read())
    stored_uuid = posted_body["stored_uuid"]
    access_token = posted_body["access_token"]

    verified_user = verify_token(access_token)
    user_id = verified_user["uid"]

    try:
        with connect_to_db() as db, db.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM http_claimed_uuid WHERE claim_uuid = %s AND user_id = %s",
                (stored_uuid, user_id),
            )
            if cursor.fetchall()[0][0] == 1:
                # Already taken by same user.
                pass
            else:
                cursor.execute(
                    "INSERT INTO http_claimed_uuid (claim_uuid, user_id) VALUES (%s, %s)",
                    (stored_uuid, user_id),
                )
    except psycopg2.errors.UniqueViolation:
        return {"status": "AlreadyClaimed"}
    return {"status": "Ok"}


@app.route("/http-storage/<path:uuid>", methods=["POST"])
def post(uuid):
    try:
        UUID(uuid)
    except ValueError:
        return (
            f"Not a uuid: {uuid}. POST to /http-storage/$UUID",
            400,
            {"content-type": "text/plain"},
        )

    try:
        line_count = 0
        with connect_to_db() as db, db.cursor() as cursor:
            for line in request.stream:
                try:
                    parsed_line = json.loads(line)
                    jsonschema.validate(instance=parsed_line, schema=HTTP_TYPES_SCHEMA)
                    cursor.execute(
                        "INSERT INTO http_data (claim_uuid, json_data) VALUES (%s, %s)",
                        (uuid, line.decode("utf-8")),
                    )
                    line_count += 1
                except JSONDecodeError:
                    raise InvalidFormatException(
                        f"Line {line_count}: Content is not JSON"
                    )
                except jsonschema.exceptions.ValidationError as error:
                    raise InvalidFormatException(f"Line {line_count}: {error.message}")
                return f"Stored - visit https://meeshkan.io/http-storage/{uuid} to claim the data\r\n"
    except InvalidFormatException as error:
        return error.message, 400, {"content-type": "text/plain"}


@app.route("/_ah/warmup")
def warmup():
    return "OK"


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=9094,
        debug=True,
        extra_files=["index.html", "claim.html"],
    )
