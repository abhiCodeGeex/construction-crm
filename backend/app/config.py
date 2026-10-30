import os


class Config:
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    MONGO_DB = os.getenv("MONGO_DB", "buildsuite")
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    TOKEN_HOURS = int(os.getenv("TOKEN_HOURS", "12"))
    UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/data/uploads")
    MAX_CONTENT_LENGTH = 200 * 1024 * 1024
    GST_RATE = 18.0
    TRIAL_DAYS = 14
    GRACE_DAYS = 7
    PLATFORM_GSTIN = os.getenv("PLATFORM_GSTIN", "29ABCDE1234F1Z5")
    PLATFORM_SAC = "998314"
