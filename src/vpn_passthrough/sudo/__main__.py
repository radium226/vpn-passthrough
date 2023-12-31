from sys import stdin, stdout
from io import BytesIO

import dill


if __name__ == "__main__":
    input_payload = dill.load(stdin.buffer)
    output_payload = input_payload["func"](*input_payload["args"], **input_payload["kwargs"])
    dill.dump(output_payload, stdout.buffer)