from dotenv import load_dotenv
load_dotenv()

import app,json,os

event = json.loads(os.environ["event"])
context = {}

print("App.Run")
app.run(event, context)