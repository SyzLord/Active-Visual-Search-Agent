"""Re-execute policy decisions with saved raw OCR and check encoded input hashes."""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from benchmark import load_case_pages
from search import prior, run_query


class RecordedReader:
    def __init__(self,steps):
        self.steps=steps
        self.used=0
        self.hashed=0

    def recognize(self,encoded,size,mode):
        step=self.steps[self.used]
        assert step["size"]==list(size) and step["engine_mode"]==mode
        if "input_sha256" in step:
            assert sha256(encoded).hexdigest()==step["input_sha256"]
            self.hashed+=1
        self.used+=1
        return deepcopy(step["raw_normalized"])


def check_replay(protocol_path, result_path):
    protocol=json.loads(protocol_path.read_text())
    result=json.loads(result_path.read_text())
    assert prior.digest(protocol_path)==result["protocol_sha256"]
    pages=load_case_pages(protocol)
    cases={case["id"]:case for case in protocol["cases"]}
    calls=byte_checks=0
    for row in result["rows"]:
        case=cases[row["case"]]
        task=prior.grader.parse_task({"op":"verify","fields":[{"anchor":case["date"]},{"anchor":case["text"]}]})
        trace=row["trace"]
        reader=RecordedReader(trace["steps"])
        replayed=run_query(row["policy"],task,[pages[key] for key in row["pages"]],reader)
        assert reader.used==len(trace["steps"])
        for old,new in zip(trace["steps"],replayed["steps"],strict=True):
            if "input_sha256" not in old:
                new.pop("input_sha256")
        assert json.loads(json.dumps(replayed))==trace,(row["policy"],row["case"],row["collection"])
        calls+=reader.used
        byte_checks+=reader.hashed
    return {"rows":len(result["rows"]),"ocr_calls_replayed":calls,"encoded_input_digests_verified":byte_checks,
            "new_recognizer_calls":0,"all_decisions_identical":True}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol",type=Path)
    parser.add_argument("result",type=Path)
    args=parser.parse_args()
    print(json.dumps(check_replay(args.protocol,args.result)))
