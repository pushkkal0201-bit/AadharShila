"""Distribution monitoring of research model inputs, not a live lending score."""
from __future__ import annotations
import math
from typing import Sequence


def population_stability_index(reference_counts: Sequence[int],current_counts: Sequence[int], min_records=100):
    """PSI is descriptive drift; it is not model accuracy or evidence of bias-free lending."""
    if len(reference_counts)<2 or len(reference_counts)!=len(current_counts):
        raise ValueError('Matched feature bin arrays required')
    if any(not isinstance(v,int) or v<0 for v in list(reference_counts)+list(current_counts)):
        raise ValueError('Counts must be non-negative integers')
    a,b=sum(reference_counts),sum(current_counts)
    if a<min_records or b<min_records:
        return {'status':'INSUFFICIENT_SAMPLE','psi':None,'reference_n':a,'current_n':b,
                'note':'No drift decision with an undersized monitoring sample.'}
    k=len(reference_counts)
    smooth=0.5
    pa=[(n+smooth)/(a+smooth*k) for n in reference_counts]
    pb=[(n+smooth)/(b+smooth*k) for n in current_counts]
    psi=sum((y-x)*math.log(y/x) for x,y in zip(pa,pb))
    return {'status':'CALCULATED','psi':round(psi,6),'reference_n':a,'current_n':b,
            'note':'Descriptive shift only. Requires calibration and real-outcome evaluation before model deployment.'}
