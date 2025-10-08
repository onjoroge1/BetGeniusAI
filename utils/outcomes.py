from typing import Optional

H, D, A = "H", "D", "A"
HOME_ALIASES = {"H", "HOME", "HOME_TEAM", "1"}
DRAW_ALIASES = {"D", "DRAW", "X", "0"}
AWAY_ALIASES = {"A", "AWAY", "AWAY_TEAM", "2"}

def normalize_outcome(x: Optional[str]) -> Optional[str]:
    """
    Normalize outcome codes to standard H/D/A format.
    
    Args:
        x: Input outcome string (various formats accepted)
        
    Returns:
        'H', 'D', 'A', or None if unrecognized
        
    Examples:
        normalize_outcome('HOME') -> 'H'
        normalize_outcome('1') -> 'H'
        normalize_outcome('X') -> 'D'
        normalize_outcome('AWAY') -> 'A'
    """
    if x is None:
        return None
    
    u = str(x).strip().upper()
    
    if u in HOME_ALIASES:
        return H
    if u in DRAW_ALIASES:
        return D
    if u in AWAY_ALIASES:
        return A
    
    # Common fallbacks
    if u.startswith("HOME"):
        return H
    if u.startswith("DRAW"):
        return D
    if u.startswith("AWAY"):
        return A
    
    return None  # Make callers handle unexpected values
