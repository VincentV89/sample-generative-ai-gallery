"""Seed the preview BaseResourceTable with base portraits sliced from docs/images/sample.jpg.

Usage: seed_base_resources.py <region> <bucket> <table> <sample.jpg>
Each portrait is registered for theme 'ancient_rome' and every skin tone the frontend offers,
so POST /apis/images/upload always finds a base image.
"""
import sys
from io import BytesIO

import boto3
from PIL import Image

THEME = "ancient_rome"
SKINS = ["light_pale_white", "white_fair", "medium_white_to_olive", "olive_tone", "light_brown", "dark_brown"]
PORTRAITS = [
    ("male", "A blacksmith of the Subura, you forged the iron that kept Rome's legions marching."),
    ("female", "Born into a wealthy family on the Palatine, you hosted banquets for senators and poets."),
    ("male", "A tailor near the Forum, you stitched the togas worn by magistrates on festival days."),
    ("female", "A priestess of Ceres, you led the harvest rites that blessed the fields beyond the city walls."),
    ("female", "A scribe's daughter, you copied Greek scrolls by lamplight for the libraries of Rome."),
    ("male", "A butcher at the Macellum, you were known across the market for honest weights and loud jokes."),
    ("male", "A travelling musician, you played the lyre at weddings from Ostia to Tibur."),
    ("male", "A scholar and record keeper, you wrote the city's chronicles in the Tabularium."),
]


def main(region, bucket, table, sample_path):
    s3 = boto3.client("s3", region_name=region)
    ddb = boto3.client("dynamodb", region_name=region)
    strip = Image.open(sample_path).convert("RGB")
    panel = strip.width / len(PORTRAITS)
    for i, (gender, story) in enumerate(PORTRAITS):
        left, right = int(i * panel) + 8, int((i + 1) * panel) - 8
        img = strip.crop((left, 0, right, strip.height))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=90)
        key = f"base-image/{THEME}/{i:02d}-{gender}.jpeg"
        s3.put_object(Bucket=bucket, Key=key, Body=buf.getvalue(), ContentType="image/jpeg")
        for skin in SKINS:
            ddb.put_item(TableName=table, Item={
                "PK": {"S": f"#THEME#{THEME}#GENDER#{gender}#SKIN#{skin}"},
                "SK": {"S": f"#UUID#{THEME}-{i:02d}"},
                "base_image_object_key": {"S": key},
                "story": {"S": story},
            })
        print(f"seeded {key}")


if __name__ == "__main__":
    main(*sys.argv[1:5])
