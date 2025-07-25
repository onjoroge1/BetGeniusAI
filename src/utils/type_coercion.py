"""
Type Coercion Guardrail - Immediate Tightening Implementation
Ensures all numpy types are converted to Python scalars before database writes
"""

import numpy as np
import pandas as pd
from typing import Any, Dict, List, Union

def ensure_py_types(data: Union[Dict, List, pd.DataFrame, Any]) -> Any:
    """
    Convert all numpy types to Python scalars to prevent database write errors
    
    Args:
        data: Input data structure (dict, list, DataFrame, or single value)
        
    Returns:
        Data with all numpy types converted to Python equivalents
    """
    
    if isinstance(data, dict):
        return {k: ensure_py_types(v) for k, v in data.items()}
    
    elif isinstance(data, list):
        return [ensure_py_types(item) for item in data]
    
    elif isinstance(data, pd.DataFrame):
        # Convert DataFrame columns
        df_copy = data.copy()
        for col in df_copy.columns:
            if df_copy[col].dtype.kind in ['i', 'u', 'f', 'b']:  # numeric or boolean
                df_copy[col] = df_copy[col].astype(object).apply(ensure_py_types)
        return df_copy
    
    elif isinstance(data, pd.Series):
        return data.astype(object).apply(ensure_py_types)
    
    elif isinstance(data, (np.integer, np.int8, np.int16, np.int32, np.int64,
                          np.uint8, np.uint16, np.uint32, np.uint64)):
        return int(data)
    
    elif isinstance(data, (np.floating, np.float16, np.float32, np.float64)):
        return float(data)
    
    elif isinstance(data, np.bool_):
        return bool(data)
    
    elif isinstance(data, np.ndarray):
        return data.tolist()
    
    elif isinstance(data, (np.str_, np.bytes_)):
        return str(data)
    
    # Return as-is if already Python type
    return data

def validate_db_write_data(data: Dict) -> Dict:
    """
    Validate and clean data before database write operations
    
    Args:
        data: Dictionary containing data to be written to database
        
    Returns:
        Cleaned data safe for database operations
    """
    
    cleaned_data = ensure_py_types(data)
    
    # Additional validation
    for key, value in cleaned_data.items():
        # Handle None/NaN values
        if pd.isna(value):
            cleaned_data[key] = None
        
        # Ensure finite numeric values
        elif isinstance(value, (int, float)):
            if not np.isfinite(value):
                cleaned_data[key] = None
    
    return cleaned_data

def safe_db_insert(session, model_class, data_dict: Dict):
    """
    Safely insert data into database with type coercion
    
    Args:
        session: SQLAlchemy session
        model_class: Database model class
        data_dict: Data dictionary to insert
    """
    
    # Clean data
    cleaned_data = validate_db_write_data(data_dict)
    
    # Create model instance
    instance = model_class(**cleaned_data)
    
    # Insert
    session.add(instance)
    session.commit()
    
    return instance

def test_type_coercion():
    """Test the type coercion utility"""
    
    print("Testing type coercion guardrail...")
    
    # Test data with numpy types
    test_data = {
        'numpy_int': np.int64(42),
        'numpy_float': np.float64(3.14159),
        'numpy_bool': np.bool_(True),
        'numpy_array': np.array([1, 2, 3]),
        'regular_int': 10,
        'regular_float': 2.718,
        'regular_bool': False,
        'nested_dict': {
            'inner_numpy': np.float32(1.414),
            'inner_list': [np.int32(5), np.float64(6.28)]
        },
        'list_with_numpy': [np.int16(1), np.float32(2.5), np.bool_(False)]
    }
    
    print("Original data types:")
    for key, value in test_data.items():
        print(f"  {key}: {type(value)} = {value}")
    
    # Convert types
    cleaned_data = ensure_py_types(test_data)
    
    print("\nCleaned data types:")
    for key, value in cleaned_data.items():
        print(f"  {key}: {type(value)} = {value}")
    
    # Verify all types are Python native
    def check_python_types(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                check_python_types(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                check_python_types(v, f"{path}[{i}]")
        else:
            if isinstance(obj, (np.number, np.ndarray, np.bool_)):
                print(f"WARNING: Found numpy type at {path}: {type(obj)}")
            else:
                print(f"✓ Python type at {path}: {type(obj)}")
    
    print("\nType validation:")
    check_python_types(cleaned_data)
    
    print("Type coercion test completed!")

if __name__ == "__main__":
    test_type_coercion()