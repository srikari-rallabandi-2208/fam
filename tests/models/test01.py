from fam.blood import GenericObject, StringField, ReferenceFrom, ReferenceTo, BoolField, NumberField, DictField

NAMESPACE = "glowinthedark.co.uk/test/1"


class Dog(GenericObject):
    use_cas = True
    allow_decoration = True
    fields = {
        "name": StringField(),
        "owner_id": ReferenceTo(NAMESPACE, "person", delete="cascade")
        }

    def talk(self):
        return "woof"


class JackRussell(Dog):

    fields = {
        "age": NumberField(),
        }

    def talk(self):
        return "Yap"


class Cat(GenericObject):
    use_cas = True
    allow_decoration = False
    fields = {
        "name": StringField(),
        "legs": NumberField(),
        "owner_id": ReferenceTo(NAMESPACE, "person")
        }


class Person(GenericObject):
    use_cas = True
    allow_decoration = False
    fields = {
        "name": StringField(),
        "cats": ReferenceFrom(NAMESPACE, "cat", "owner_id", delete="cascade"),
        "dogs": ReferenceFrom(NAMESPACE, "dog", "owner_id")
        }


routes = {"cat":Cat,
      "dog":Dog,
      "person":Person,
      }

