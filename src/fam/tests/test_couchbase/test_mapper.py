import os
import shutil
import unittest
from fam.database import CouchbaseWrapper
from fam.mapper import ClassMapper
from fam.schema.validator import ModelValidator
from fam.exceptions import FamValidationError
from fam.tests.test_couchbase.config import *
from fam.tests.models import test01
from fam.tests.models.test01 import Dog, Cat, Person, JackRussell
from fam.blud import StringField

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(THIS_DIR, "data")
DESIGN_PATH = os.path.join(DATA_PATH, "design_ref.json")

class MapperValidationTests(unittest.TestCase):

    def test_make_a_validator(self):

        mapper = ClassMapper([Dog, Cat, Person, JackRussell])
        validator = ModelValidator(None, classes=[Dog, Cat, Person, JackRussell])
        self.db = CouchbaseWrapper(mapper, COUCHBASE_URL, COUCHBASE_BUCKET_NAME, username='Administrator',password='GU$dcRS4',scope=COUCHBASE_SCOPE_NAME,read_only=False)
        self.db.setCollection("pets")
        self.db.update_designs()

        paul = Person(name="paul")
        paul.save(self.db)
        cat = Cat(name="whiskers", owner_id=paul.key, legs=4)
        cat.save(self.db)


        self.assertEqual(cat.owner, paul)
        self.assertEqual(cat.owner.name, "paul")

        cat = Cat(name="puss", owner_id=paul.key)

        self.assertRaises(FamValidationError, cat.save, self.db)

        self.db.session.close()
