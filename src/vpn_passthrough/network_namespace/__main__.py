from sys import stdin, stdout
import dill
from io import BytesIO


if __name__ == "__main__":
    input_payload = dill.load(stdin.buffer)
    print(input_payload)
    output_payload = input_payload["func"](*input_payload["args"], **input_payload["kwargs"])
    dill.dump(output_payload, stdout.buffer)