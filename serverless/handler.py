import json
import os

# /test1/?foo=id
def test1(event, context):
    input = event['queryStringParameters']['foo']

    stream = os.popen(input)  # Noncompliant (S2076)
    output = stream.read()

    body = {
        "input": input,
        "output": output
    }

    response = {
        "statusCode": 200,
        "body": json.dumps(body)
    }

    return response

# /test2?foo=id
def test2(event, context):
    input = event['queryStringParameters']['foo']

    stream = os.popen(input)  # Noncompliant (S2076)
    output = stream.read()

    body = {
        "input": input,
        "output": output
    }

    response = {
        "statusCode": 200,
        "body": json.dumps(body)
    }

    return response

# /test3/?foo=id
def test3(event, context):
    input = event['queryStringParameters']['foo']

    stream = os.popen(input)  # Noncompliant (S2076)
    output = stream.read()

    body = {
        "input": input,
        "output": output
    }

    response = {
        "statusCode": 200,
        "body": json.dumps(body)
    }

    return response