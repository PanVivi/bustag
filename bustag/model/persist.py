'''
persist model required files
'''
import os
import pickle


def dump_model(path, models):
    '''
    Atomically replace model files so a restart during training cannot leave a
    half-written pickle behind.
    '''
    temp_path = path + '.tmp'
    try:
        with open(temp_path, 'wb') as f:
            pickle.dump(models, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def load_model(path):
    with open(path, 'rb') as f:
        models = pickle.load(f)
    return models
