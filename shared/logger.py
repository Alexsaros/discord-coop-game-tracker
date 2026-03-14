
def log(message):
    message = str(message)
    print(message)
    with open("log.log", "a", encoding="utf-8") as f:
        f.write(message + "\n")
