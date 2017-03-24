import simplejson as json
import hashlib
import copy
from fam.fam_json import object_default

from base64 import b64encode


from fam.utils import requests_shim as requests

from .couchdb import CouchDBWrapper, ResultWrapper

class SyncGatewayWrapper(CouchDBWrapper):

    ## the option stale=false forces the view to be indexed on read. Sync_gateway does not index on write!!
    # VIEW_URL = "%s/%s/_design/%s/_view/%s?stale=false&key=\"%s\""

    # this function is different from the base version in that it adds the rev from the meta into the doc
    FOREIGN_KEY_MAP_STRING = '''function(doc, meta) {
    var resources = %s;
    if (resources.indexOf(doc.type) != -1 && doc.namespace == \"%s\"){
        doc._rev = meta.rev;
        emit(doc.%s, doc);
    }
}'''

    database_type = "sync_gateway"

    def __init__(self, mapper, db_url, db_name,
                 auth_url=None,
                 username=None,
                 password=None,
                 validator=None,
                 read_only=False):


        self.mapper = mapper
        self.validator = validator
        self.read_only = read_only

        self.db_name = db_name
        self.db_url = db_url
        self.username = username
        self.password = password
        self.auth_url = auth_url
        self.session = requests.Session()

        url = "%s/%s" % (db_url, db_name)

        print url
        rsp = self.session.get(url)

        self.cookies = {}

        if rsp.status_code == 404:
            raise Exception("Unknown database and you can't create them in the sync gateway")

    def authenticate(self):
        if self.username is None:
            raise Exception("failed to authenticate no username")

        userAndPass = b64encode(b"paul:bumbum").decode("ascii")
        headers = { 'Authorization' : 'Basic %s' %  userAndPass }

        rsp = self.session.get(self.auth_url, headers=headers)
        if rsp.status_code == 200:
            self.cookies = rsp.cookies
        else:
            raise Exception("failed to authenticate")


    def _wrapper_from_view_json(self, as_json):
        return ResultWrapper.from_gateway_view_json(as_json)


    # def changes(self, since=None, channels=None, limit=None):
    #     raise NotImplementedError("Haven't done changes for sync gateway yet")


    def sync_up(self):
        pass

    def sync_down(self):
        pass


    def purge(self, key):

        if self.read_only:
            raise Exception("This db is read only")

        data = {
            key: ["*"]
        }

        rsp = self.session.post("%s/%s/_purge" % (self.db_url, self.db_name), data=json.dumps(data))

        if rsp.status_code == 200 or rsp.status_code == 202:
            return


    def user(self, username):
        url = "%s/%s/_user/%s" % (self.db_url, self.db_name, username)
        rsp = self.session.get(url)
        if rsp.status_code == 200:
            return rsp.json()
        else:
            return None

    def role(self, role_name):
        url = "%s/%s/_role/%s" % (self.db_url, self.db_name, role_name)
        rsp = self.session.get(url)
        if rsp.status_code == 200:
            return rsp.json()
        else:
            return None


    def ensure_role(self, role_name):

        role_info = self.role(role_name)
        if role_info is None:
            data = {
                "name": role_name,
                "db": self.db_name
            }

            url = "%s/%s/_role/%s" % (self.db_url, self.db_name, role_name)

            rsp = self.session.put(url, data=json.dumps(data, indent=4, sort_keys=True, default=object_default),
                                   headers={"Content-Type": "application/json", "Accept": "application/json"})
            if rsp.status_code == 200 or rsp.status_code == 201:
               return True
            else:
                return False
        else:
            return True


    def ensure_user_role(self, username, role):

        user_info = self.user(username)
        roles = user_info["admin_roles"]

        if not role in roles:
            roles.append(role)

            url = "%s/%s/_user/%s" % (self.db_url, self.db_name, username)

            rsp = self.session.put(url, data=json.dumps(user_info, indent=4, sort_keys=True, default=object_default),
                                   headers={"Content-Type": "application/json", "Accept": "application/json"})
            if rsp.status_code == 200 or rsp.status_code == 201:
               return True
            else:
                return False
        else:
            return True


    def view(self, name, **kwargs):
        return super(SyncGatewayWrapper, self).view(name, stale="false", **kwargs)

    # @auth
    def get_design(self, key):

        url = "%s/%s/%s" % (self.db_url, self.db_name, key)
        print url
        rsp = self.session.get(url)

        if rsp.status_code == 200:
            return rsp.json()
        if rsp.status_code == 500:
            return None
        if rsp.status_code == 400:
            return None
        if rsp.status_code == 404:
            return None
        raise Exception("Unknown Error getting cb doc: %s %s" % (rsp.status_code, rsp.text))



    def ensure_design_doc(self, key, doc):

        if self.read_only:
            raise Exception("This db is read only")

        # first put it into dev
        dev_key = key.replace("_design/", "_design/dev_")
        dev_doc = copy.deepcopy(doc)
        dev_doc["_id"] = dev_key
        self._set(dev_key, dev_doc)

        # then get it back again to compare

        existing = self.get_design(key)

        existing_dev = self.get_design(dev_key)

        if existing == existing_dev:
            print "************  design doc %s up to date ************" % key
        else:
            print "************  updating design doc %s ************" % key
            print "new_design: ", doc
            self._set(key, doc)



    def _raw_design_doc(self):

        design_doc = {
            "views": {
                "all": {
                    "map": """function(doc, meta) {
                        doc._rev = meta.rev;
                        emit(doc.type, doc);
                    }
                    """
                }
            }
        }

        return design_doc
