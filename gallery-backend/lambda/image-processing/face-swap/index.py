import json
import boto3
import os
import urllib.parse
from io import BytesIO

ddb_client = boto3.client('dynamodb')
s3_client = boto3.client('s3')
sagemaker_runtime = boto3.client('sagemaker-runtime')

BUCKET_NAME = os.environ['BUCKET_NAME']
RESULT_OBJECT_PATH = os.environ['RESULT_OBJECT_PATH']
# When no FaceChain endpoint is configured (e.g. development previews without a GPU endpoint),
# a simple Pillow composite of the user's face on the base image is written instead.
FACECHAIN_SAGEMAKER_ENDPOINT_NAME = os.environ.get('FACECHAIN_SAGEMAKER_ENDPOINT_NAME', '')
DDB_AMAZON_BEDROCK_GALLERY_PROCESS_TABLE_NAME = os.environ['DDB_AMAZON_BEDROCK_GALLERY_PROCESS_TABLE_NAME']

def lambda_handler(event, context):
    s3_event = event['Records'][0]['s3']
    bucket_name = s3_event['bucket']['name']
    encoded_object_key = s3_event['object']['key']
    source_object_key = urllib.parse.unquote_plus(encoded_object_key) # user's cropped face image
    source_object_filename = os.path.basename(source_object_key) # source_object_filename: {current_time}-{user_id}-{theme}-{gender}-{skin}-{unique_id}.jpeg
    uuid = os.path.splitext(source_object_filename)[0] 
    user_id = uuid.split('-')[1]
    theme = uuid.split('-')[2]
    gender = uuid.split('-')[3]
    skin = uuid.split('-')[4]
    
    ddb_response = ddb_client.query(
        TableName=DDB_AMAZON_BEDROCK_GALLERY_PROCESS_TABLE_NAME,
        KeyConditionExpression='#pk = :pk',
        ExpressionAttributeNames={
            '#pk': 'PK'
        },
        ExpressionAttributeValues={
            ':pk': {'S': f'#UUID#{uuid}'}
        }
    )
    
    if not ddb_response['Items']:
        raise Exception(f"Could not find image with uuid({uuid})")
    
    target_object_key = ddb_response['Items'][0]['base_image_object_key']['S']
    output_object_key = os.path.join(RESULT_OBJECT_PATH, source_object_filename)

    request_body = {
        'uuid': uuid,
        'bucket': BUCKET_NAME,
        'source': source_object_key,
        'target': target_object_key,
        'output': output_object_key
    }
    
    if not FACECHAIN_SAGEMAKER_ENDPOINT_NAME:
        write_preview_composite(source_object_key, target_object_key, output_object_key)
        return {
            'statusCode': 200,
            'body': json.dumps('Preview composite complete')
        }

    sagemaker_runtime.invoke_endpoint(
        EndpointName=FACECHAIN_SAGEMAKER_ENDPOINT_NAME,
        ContentType='application/json',
        Body=json.dumps(request_body)
    )
    
    return {
        'statusCode': 200,
        'body': json.dumps('Face swap complete')
    }


def _load_image(key):
    from PIL import Image
    body = s3_client.get_object(Bucket=BUCKET_NAME, Key=key)['Body'].read()
    return Image.open(BytesIO(body)).convert('RGB')


def write_preview_composite(source_key, target_key, output_key):
    """Paste the cropped face as a framed circular inset on the base image."""
    from PIL import Image, ImageDraw, ImageOps
    base = _load_image(target_key)
    face = _load_image(source_key)

    size = max(64, int(min(base.size) * 0.34))
    face = ImageOps.fit(face, (size, size))
    mask = Image.new('L', (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)

    border = max(4, size // 40)
    margin = max(8, size // 10)
    x = base.width - size - margin
    y = base.height - size - margin
    ImageDraw.Draw(base).ellipse((x - border, y - border, x + size + border, y + size + border), fill=(245, 236, 214))
    base.paste(face, (x, y), mask)

    buffered = BytesIO()
    base.save(buffered, format='JPEG', quality=90)
    s3_client.put_object(Bucket=BUCKET_NAME, Key=output_key, Body=buffered.getvalue(), ContentType='image/jpeg')
