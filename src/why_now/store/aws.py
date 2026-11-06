"""A Store kept in AWS: records in DynamoDB, files in S3.

Every document has a DynamoDB record, so listing always reads one table, in key order.
A small document lives in its record as JSON text. Job ads, evidence packs and any
document too big for a record live in S3 instead, and the record names the file.

Each save writes a file with a new name and then removes the file the record named
before. So two saves racing on one document can't remove each other's file, and a
record never names a file that isn't there.

The table's partition key is `collection` and its sort key is `key`, both strings.
The AWS setup creates the bucket and the table. This class only reads and writes them.
"""

import json
import uuid
from collections.abc import Callable, Iterator
from typing import Any

from why_now.store import split_name

# Collections that are always files: job ads and evidence packs are large and read
# whole, and S3 costs much less than DynamoDB to keep them in.
FILE_COLLECTIONS = frozenset({"board_ads", "packs"})

# Makes an AWS client for a service name, such as `boto3.client`.
ClientFactory = Callable[[str], Any]


class AwsStore:
    def __init__(
        self, bucket: str, table: str, client_factory: ClientFactory, *, inline_max_bytes: int
    ):
        self.bucket = bucket
        self.table = table
        self.inline_max_bytes = inline_max_bytes
        self._s3 = client_factory("s3")
        self._db = client_factory("dynamodb")

    def put(self, collection: str, key: str, doc: dict) -> None:
        item = _record_key(collection, key)
        body = json.dumps(doc, ensure_ascii=False)
        data = body.encode("utf-8")
        if collection in FILE_COLLECTIONS or len(data) > self.inline_max_bytes:
            name = f"{collection}/{uuid.uuid4().hex}.json"
            # The file goes first, so a record never names a file that isn't there.
            self._s3.put_object(
                Bucket=self.bucket, Key=name, Body=data, ContentType="application/json"
            )
            item |= {"file": {"S": name}}
        else:
            item |= {"doc": {"S": body}}
        replaced = self._db.put_item(TableName=self.table, Item=item, ReturnValues="ALL_OLD")
        self._remove_file(replaced.get("Attributes"))

    def get(self, collection: str, key: str) -> dict | None:
        try:
            return self._read(collection, key)
        except self._s3.exceptions.NoSuchKey:
            # Another save replaced the document between reading its record and its
            # file. The record now names the newer file.
            return self._read(collection, key)

    def list(self, collection: str, prefix: str = "") -> Iterator[tuple[str, dict]]:
        split_name(collection)
        condition = "#c = :c"
        names = {"#c": "collection"}
        values: dict[str, Any] = {":c": {"S": collection}}
        if prefix:  # DynamoDB refuses an empty string in a key condition
            condition += " AND begins_with(#k, :p)"
            names["#k"] = "key"
            values[":p"] = {"S": prefix}
        pages = self._db.get_paginator("query").paginate(
            TableName=self.table,
            KeyConditionExpression=condition,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ConsistentRead=True,
        )
        for page in pages:
            for record in page["Items"]:
                key = record["key"]["S"]
                try:
                    doc = self._doc(record)
                except self._s3.exceptions.NoSuchKey:
                    doc = self.get(collection, key)  # replaced or deleted while listing
                if doc is not None:
                    yield key, doc

    def delete(self, collection: str, key: str) -> None:
        removed = self._db.delete_item(
            TableName=self.table, Key=_record_key(collection, key), ReturnValues="ALL_OLD"
        )
        self._remove_file(removed.get("Attributes"))

    def _read(self, collection: str, key: str) -> dict | None:
        reply = self._db.get_item(
            TableName=self.table, Key=_record_key(collection, key), ConsistentRead=True
        )
        record = reply.get("Item")
        return None if record is None else self._doc(record)

    def _doc(self, record: dict) -> dict:
        name = _file_of(record)
        if name is None:
            return json.loads(record["doc"]["S"])
        reply = self._s3.get_object(Bucket=self.bucket, Key=name)
        return json.loads(reply["Body"].read().decode("utf-8"))

    def _remove_file(self, record: dict | None) -> None:
        name = _file_of(record)
        if name is not None:
            self._s3.delete_object(Bucket=self.bucket, Key=name)


def _record_key(collection: str, key: str) -> dict:
    split_name(collection)
    split_name(key)
    return {"collection": {"S": collection}, "key": {"S": key}}


def _file_of(record: dict | None) -> str | None:
    """The S3 file a record names, or None if the document is in the record itself."""
    return record["file"]["S"] if record and "file" in record else None
