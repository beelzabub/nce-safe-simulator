import os


app_user = os.getenv("APP_USER")
app_pass = os.getenv("APP_PASS")

print(f"Printing CI/CD variables with Python ...")
print(f"  APP_USER: {app_user}")
print(f"  APP_PASS: {app_pass}")
print(f"That was awesome")
