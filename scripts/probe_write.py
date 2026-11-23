import os
import tempfile

base = r"D:\lanchain rag项目\.tmp"
os.makedirs(os.path.join(base, "manual-test"), exist_ok=True)
p = os.path.join(base, "manual-test", "python_dotenv-1.2.4-py3-none-any.whl.metadata")
try:
    with open(p, "wb") as f:
        f.write(b"x")
    print("manual exact-name write ok")
except Exception as e:  # noqa: BLE001
    print("manual exact-name fail:", type(e).__name__, e)

d = tempfile.mkdtemp(dir=base)
print("mkdtemp:", d)
p2 = os.path.join(d, "a.whl.metadata")
try:
    with open(p2, "wb") as f:
        f.write(b"x")
    print("mkdtemp write ok")
except Exception as e:  # noqa: BLE001
    print("mkdtemp write fail:", type(e).__name__, e)

print("listdir base:", os.listdir(base)[:10])
