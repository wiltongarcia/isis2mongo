from mongoengine import *

connect("index")

class cds(Document):
    db_id = IntField()
    text = StringField()
    field = StringField()

x = cds(db_id=2,text="teste",field="123")
x.save()
    

    