import app, os

event = json.loads(os.environ["event"])
context = json.loads(os.environ["context"])

print("App.Run")
app.run(event, context)