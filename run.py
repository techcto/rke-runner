from dotenv import load_dotenv
load_dotenv()

import app,json,os

print(str(os.environ))

event = json.loads(os.environ["event"])
context = {}

print("App.Run")
app.run(event, context)