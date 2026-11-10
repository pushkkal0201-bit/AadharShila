"""Immutable local research candidate registry. Digest checks are not institutional approval."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from .risk_serving import MAX_ARTIFACT_BYTES, ResearchModelUnavailable, validate_research_artifact


def register(artifact_file: Path, registry_directory: Path) -> dict:
    """Archive exactly one inert, validated synthetic candidate under its content digest."""
    artifact_file=Path(artifact_file)
    raw=artifact_file.read_bytes()
    if len(raw)>MAX_ARTIFACT_BYTES:raise ResearchModelUnavailable('Oversized research artifact')
    document=json.loads(raw)
    validate_research_artifact(document)
    digest=hashlib.sha256(raw).hexdigest()
    registry_directory=Path(registry_directory)
    registry_directory.mkdir(parents=True,exist_ok=True)
    final=registry_directory/digest
    if final.exists():
        verify(final)
        return {'status':'ALREADY_REGISTERED','model_digest':digest,'artifact_path':str(final/'artifact.json'),
                'registry_entry':str(final)}
    temporary=Path(tempfile.mkdtemp(prefix='.research-',dir=registry_directory))
    try:
        (temporary/'artifact.json').write_bytes(raw)
        metadata={'status':'RESEARCH_CANDIDATE_NOT_AUTHORIZED',
                  'artifact_sha256':digest,'synthetic':True,
                  'model_family':document['evaluation']['model_family'],
                  'data_sha256':document['evaluation']['data_sha256'],
                  'manifest_sha256':document['evaluation']['manifest_sha256'],
                  'artifact_format':document['artifact_format'],
                  'parameter_sha256':document['parameter_sha256'],
                  'note':'A file digest does not certify data rights, fairness, credit accuracy or lending authority.'}
        (temporary/'entry.json').write_text(json.dumps(metadata,indent=2,sort_keys=True),encoding='utf-8')
        os.rename(temporary,final)
    finally:
        if temporary.exists():shutil.rmtree(temporary)
    return {'status':'REGISTERED_RESEARCH_ONLY','model_digest':digest,
            'artifact_path':str(final/'artifact.json'),'registry_entry':str(final)}


def verify(entry_directory: Path) -> dict:
    entry_directory=Path(entry_directory)
    if entry_directory.is_symlink():raise ResearchModelUnavailable('Registry entry cannot be a symbolic link')
    metadata=json.loads((entry_directory/'entry.json').read_text(encoding='utf-8'))
    artifact_path=entry_directory/'artifact.json'
    if artifact_path.is_symlink():raise ResearchModelUnavailable('Registry artifact cannot be a symbolic link')
    raw=artifact_path.read_bytes()
    digest=hashlib.sha256(raw).hexdigest()
    if digest!=metadata.get('artifact_sha256') or digest!=entry_directory.name:
        raise ResearchModelUnavailable('Research registry artifact integrity mismatch')
    validate_research_artifact(json.loads(raw))
    if metadata.get('status')!='RESEARCH_CANDIDATE_NOT_AUTHORIZED':
        raise ResearchModelUnavailable('Research registry status cannot authorize lending')
    return {'status':'INTEGRITY_VERIFIED_NOT_AUTHORIZED','model_digest':digest}


def main():
    p=argparse.ArgumentParser(description='Synthetic-only research artifact registry (never an approval system)')
    sub=p.add_subparsers(dest='action',required=True)
    add=sub.add_parser('add');add.add_argument('--artifact',type=Path,required=True);add.add_argument('--registry',type=Path,required=True)
    check=sub.add_parser('verify');check.add_argument('--entry',type=Path,required=True)
    args=p.parse_args()
    print(json.dumps(register(args.artifact,args.registry) if args.action=='add' else verify(args.entry),indent=2))

if __name__=='__main__':main()
