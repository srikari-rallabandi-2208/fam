import simplejson as json
from fam.fam_json import object_default
import jsonschema
from copy import deepcopy

from fam.exceptions import *
from fam.constants import *
from fam.utils import requests_shim as requests
from fam.database.base import BaseDatabase, FamDbAuthException


class ResultWrapper(object):

    def __init__(self, key, rev, value):
        self.key = key
        self.rev = rev
        self.value = value

    @classmethod
    def from_couchdb_json(cls, as_json):
        key = as_json["_id"]
        rev = as_json.get("_rev")
        if rev is not None:
            rev = rev
            del as_json["_rev"]
        else:
            rev = None
        del as_json["_id"]
        value = as_json
        return cls(key, rev, value)

    @classmethod
    def from_couchdb_view_json(cls, as_json):
        key = as_json["id"]
        rev = as_json["value"]["_rev"]
        value = deepcopy(as_json["value"])
        del value["_id"]
        del value["_rev"]
        return cls(key, rev, value)

    @classmethod
    def from_gateway_view_json(cls, as_json):
        # the format of this seems to be changing quite a bit
        try:
            key = as_json["id"]
            value = deepcopy(as_json["value"])
            sync = value.get("_sync")
            if sync is not None:
                rev = sync["rev"]
                del value["_sync"]
            elif value.get("_rev"):
                rev = as_json["value"]["_rev"]
                del value["_rev"]
            else:
                rev = None
        except KeyError, e:
            print "key error raised in from_gateway_view_json on object: %s" % json.dumps(as_json, indent=4)
            raise e
        return cls(key, rev, value)


def auth(func):
    def func_wrapper(instance, *args, **kwargs):
        try:
            return func(instance, *args, **kwargs)
        except FamDbAuthException:
            instance.authenticate()
            return func(instance, *args, **kwargs)
    return func_wrapper

class CouchDBWrapper(BaseDatabase):

    VIEW_URL = "%s/%s/_design/%s/_view/%s?key=\"%s\""

    def __init__(self, mapper, db_url, db_name, reset=False, remote_url=None, continuous=False):

        self.mapper = mapper
        self.validator = mapper.validator
        self.cookies = {}

        self.remote_url = remote_url
        self.db_name = db_name
        self.db_url = db_url


        url = "%s/%s" % (db_url, db_name)

        if reset:
            rsp = requests.get(url)
            if rsp.status_code == 200:
                rsp = requests.delete("%s/%s" % (db_url, db_name))
                if rsp.status_code == 401:
                    raise Exception("Error deleting CB database: 401 Unauthorized")
                if rsp.status_code == 400:
                    raise Exception("Error deleting CB database: 400 Bad Request")

        rsp = requests.get(url)
        if rsp.status_code == 200:
            print "exists", db_name, db_url

        if rsp.status_code == 404:
            rsp = requests.put(url)
            if rsp.status_code == 401:
                raise Exception("Error creating CB database: 401 Unauthorized")
            if rsp.status_code == 400:
                raise Exception("Error creating CB database: 400 Bad Request")
            if not(rsp.status_code == 201 or rsp.status_code == 412):
                raise Exception("Unknown Error creating cb database: %s" % rsp.status_code)

        self.continuous = continuous
        if continuous:
            self.sync_both_continuous()

    @auth
    def _get(self, key):
        url = "%s/%s/%s" % (self.db_url, self.db_name, key)
        rsp = requests.get(url)
        if rsp.status_code == 200:
            return ResultWrapper.from_couchdb_json(rsp.json())
        if rsp.status_code == 404:
            return None
        if rsp.status_code == 401:
            raise FamDbAuthException(" %s %s" % (rsp.status_code, rsp.text))
        raise Exception("Unknown Error getting cb doc: %s %s" % (rsp.status_code, rsp.text))


    def _set(self, key, value, rev=None):

        if self.validator is not None:
            try:
                self.validator.validate(value)
            except jsonschema.ValidationError, e:
                raise FamValidationError(e)

        value["_id"] = key
        if rev:
            value["_rev"] = rev

        url = "%s/%s/%s" % (self.db_url, self.db_name, key)
        rsp = requests.put(url, data=json.dumps(value, indent=4, sort_keys=True, default=object_default), headers={"Content-Type": "application/json", "Accept": "application/json"})
        if rsp.status_code == 200 or rsp.status_code == 201:
            if rsp.content:
                value["_rev"] = rsp.json()["rev"]
            return ResultWrapper.from_couchdb_json(value)
        else:
            raise FamResourceConflict("Unknown Error setting CBLite doc: %s %s" % (rsp.status_code, rsp.text))


    def _delete(self, key, rev):
        rsp = requests.delete("%s/%s/%s?rev=%s" % (self.db_url, self.db_name, key, rev))
        if rsp.status_code == 200 or rsp.status_code == 202:
            return
        raise FamResourceConflict("Unknown Error deleting cb doc: %s %s" % (rsp.status_code, rsp.text))


    def _wrapper_from_view_json(self, as_json):
        return ResultWrapper.from_couchdb_view_json(as_json)


    def view(self, name, key):
        design_doc_id, view_name = name.split("/")
        url = self.VIEW_URL % (self.db_url, self.db_name, design_doc_id, view_name, key)
        rsp = requests.get(url)

        if rsp.status_code == 200:
            results = rsp.json()
            rows = results["rows"]
            return [self._wrapper_from_view_json(row) for row in rows]

        raise Exception("Unknown Error view cb doc: %s %s %s" % (rsp.status_code, rsp.text, url))

    def authenticate(self):
        pass


    @auth
    def changes(self, since=None, channels=None, limit=None, feed=None):
        url = "%s/%s/_changes" % (self.db_url, self.db_name)
        params = {"include_docs":"true"}
        if since is not None:
            params["since"] = since
        if channels is not None:
            params["filter"] = "sync_gateway/bychannel"
            params["channels"] = ",".join(channels)
        if limit is not None:
            params["limit"] = limit
        if feed is not None:
            params["feed"] = feed
            if feed in ("longpoll", "continuous"):
                params["timeout"] = 60000
        rsp = requests.get(url, params=params, cookies=self.cookies)
        if rsp.status_code == 200:
            results = rsp.json()
            last_seq = results.get("last_seq")
            rows = results.get("results")
            return last_seq, [ResultWrapper.from_couchdb_json(row["doc"]) for row in rows if "doc" in row.keys() and row["doc"].get(TYPE_STR) is not None]
        if rsp.status_code == 404:
            return None, None
        if rsp.status_code == 403:
            raise FamDbAuthException()
        raise Exception("Unknown Error getting CB doc: %s %s" % (rsp.status_code, rsp.text))



    def sync_both_continuous(self):
        self.sync_up(continuous=True)
        self.sync_down(continuous=True)


    def sync_up(self, continuous=False):
        if self.remote_url is not None:
            attrs = {"create_target": False,
                     "source": self.db_name,
                     "target": self.remote_url}

            if continuous:
                attrs["continuous"] = True
            else:
                if self.continuous:
                    return

            headers = {"Content-Type": "application/json",
                       }

            rsp = requests.post("%s/_replicate" % self.db_url, data=json.dumps(attrs), headers=headers)
            if rsp.status_code == 200:
                return
            raise Exception("Unknown Error syncing up to remote: %s %s" % (rsp.status_code, rsp.text))


    def flush(self):

        rsp = requests.post("%s/%s/_ensure_full_commit" % (self.db_url, self.db_name))
        if rsp.status_code <= 201:
                return
        raise Exception("Unknown Error _ensure_full_commit in remote: %s %s" % (rsp.status_code, rsp.text))


    def sync_down(self, continuous=False):

        if self.remote_url is not None:
            attrs = {"create_target": False,
                     "source": self.remote_url,
                     "target": self.db_name}

            if continuous:
                attrs["continuous"] = True
            else:
                if self.continuous:
                    return

            rsp = requests.post("%s/_replicate" % self.db_url, data=json.dumps(attrs), headers={"Content-Type": "application/json"})
            if rsp.status_code == 200:
                return
            raise Exception("Unknown Error syncing down to remote: %s %s" % (rsp.status_code, rsp.text))

    def __getattr__(self, name):
        return self._get(name)


    def update_designs(self):

        doc_id = "_design/raw"

        design_doc = {
            "_id": doc_id,
            "views": {
                "all": {
                    "map": "function(doc) {emit(doc.type, doc);}"
                }
            }
        }

        existing = self._get(doc_id)
        self._set(doc_id, design_doc, rev=existing.rev if existing else None)

        for namespace_name, namespace in self.mapper.namespaces.iteritems():
            view_namespace = namespace_name.replace("/", "_")
            doc_id = "_design/%s" % view_namespace
            attrs = self._get_design(namespace)
            attrs["_id"] = doc_id
            existing = self._get(doc_id)
            self._set(doc_id, attrs, rev=existing.rev if existing else None)
