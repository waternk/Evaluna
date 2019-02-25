import csv
from enum import Enum
import itertools
import os
import shutil
from subprocess import check_call
import tempfile
import uuid

EXECUTIONS = {}

MODEL_EXE=os.environ.get("WQDSS_MODEL_EXE", "/model/w2_exe_linux_par")
BASE_MODEL_DIR= os.environ.get("WQDSS_BASE_MODEL_DIR", "/model")

class ExectuionState(Enum):    
    RUNNING = 'RUNNING'
    COMPLETED = 'COMPLETED'

class Execution:
    def __init__(self, exec_id, state=ExectuionState.RUNNING):
        self.state = state
        self.result = None
        self.exec_id = exec_id
        self.runs = []
        EXECUTIONS[exec_id] = self

    def add_run(self, run_dir, p):
        self.runs.append((run_dir,p))

    def clean(self):
        for (run_dir, _) in self.runs:
            shutil.rmtree(run_dir)

    def mark_complete(self):
        self.state = ExectuionState.COMPLETED

    def execute(self, params):
        permutations = generate_permutations(params)
        for (i,p) in enumerate(permutations):
            print(f'going to start run {i} with p={p}')
            run_dir = prepare_run_dir(self.exec_id, params, p)                    
            self.add_run(run_dir, p)
            exec_model(run_dir, params)
            print(f'Finished run {i}')
        
        run_scores = [(run_dir, p, get_run_score(run_dir, params)) for (run_dir, p) in self.runs]        
        best_run = max(run_scores, key= lambda x: x[2])
        return {'best_run': best_run[0], 'params': best_run[1], 'score': best_run[2]}
        


def generate_permutations(params):
    '''
    Iterates over the input files, and the defined range of values for qwd in each of these files.
    Returns the set of all relevant permutation values for the input files
    '''
    inputs = params['model_run']['input_files']
    ranges = { i['name']: values_range(float(i['min_qwd']), float(i['max_qwd']), float(i['steps'])) for i in inputs }

    # for now, get a full cartesian product of the parameter values
    run_values =  itertools.product(*ranges.values())
    input_file_names = ranges.keys()
    return [dict(zip(input_file_names, v)) for v in run_values]

def values_range(min_val, max_val, step):
    '''
    Yields all values in the range [min_val, max_val] with a given step
    '''
    cur_val = min_val
    i = 0
    while cur_val < max_val:        
        cur_val = min_val + (i * step)
        yield cur_val
        i = i + 1

def update_inputs_for_run(run_dir, params, input_values):
    # for each file in params that should be updated:
    input_files = params['model_run']['input_files']
    for i in input_files:
        # read the first contents of the input
        with open(os.path.join(run_dir, i['name']), 'r') as ifile:
            contents = ifile.readlines()

        # copy 2 header lines, and for the rest update the contents of the QWD value
        reader = csv.DictReader(contents[2:])
        with open(os.path.join(run_dir, i['name']), 'w') as ofile:
            ofile.writelines(contents[:2])
            writer = csv.DictWriter(ofile, reader.fieldnames)
            if 'QWD' in reader.fieldnames:
                out_param = 'QWD'
            else:
                out_param = 'Q'
            for row in reader:
                
                row[out_param] = input_values[i['name']]
                writer.writerow(row)


def prepare_run_dir(exec_id, params, param_values):
    '''
    Populates a temporary directory with the model files, 
    along with inputs provided by the user
    '''
    
    run_dir = tempfile.mkdtemp(prefix=f'wqdss-exec-{exec_id}')
    os.rmdir(run_dir)
    shutil.copytree(BASE_MODEL_DIR, run_dir)    
    update_inputs_for_run(run_dir, params, param_values)
    return run_dir


def exec_model(run_dir, params):    
    check_call([MODEL_EXE, run_dir])

def get_run_parameter_value(param_name, contents):
    """
    Parses outfile contents and extracts the value for the field named as `param_name` from the last row
    """

    # read the header + the last line, and strip whitespace from field names    
    header = ','.join([c.lstrip() for c in contents[0].split(',')]) +'\n'    
    reader = csv.DictReader([header, contents[-1]])
    return float(next(reader)[param_name])


def calc_param_score(value, target, score_step, desired_direction):
    
    if desired_direction > 0:
        distance = value - target
    else:
        distance = target - value

    return distance/score_step

def get_out_file_contents(run_dir, out_file):
    with open(os.path.join(run_dir, out_file), 'r') as ifile:
        contents = ifile.readlines()
    return contents


def get_run_score(run_dir, params):
    """
    Based on the params field 'model_analysis' find the run for this score
    """
    model_analysis_params = params['model_analysis']['parameters']
    out_file = params['model_analysis']['output_file']
    contents = get_out_file_contents(run_dir, out_file)
    param_scores = {}
    for param in model_analysis_params:
        param_value = get_run_parameter_value(param['name'], contents)
        param_score = calc_param_score(param_value, float(param['target']), float(param['score_step']), int(param['desired_direction']))
        param_scores[param['name']] = (param_score, float(param['weight']))

    weights = [s[1] for s in param_scores.values()]
    weighted_scores = [s[0] * s[1] for s in param_scores.values()]
    
    return sum(weighted_scores)/sum(weights)
        
def get_exec_id():
    return str(uuid.uuid4())

def get_status(exec_id):
    return EXECUTIONS[exec_id].state.value

def get_result(exec_id):
    return EXECUTIONS[exec_id].result


def execute_dss(exec_id, params):
    #TODO: extract handling the Execution to a context
    current_execution =  Execution(exec_id)
    try:
        result = current_execution.execute(params)
        current_execution.result = result
    finally:    
        current_execution.mark_complete()


    
    
