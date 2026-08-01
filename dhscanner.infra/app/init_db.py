from storage import models, db

if __name__ == '__main__':
    models.Base.metadata.create_all(bind=db.engine)
