"""
Fix International Team Logos

For World Cup, AFCON, and other international competitions, teams are countries.
This script:
1. Maps country names to their API-Football national team IDs
2. Updates the logo URLs for national teams

API-Football national team IDs are different from club team IDs.
"""

import os
import sys
import psycopg2
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

NATIONAL_TEAM_ID_MAP = {
    # AFRICA (CAF) - Verified via API-Football Dec 2025
    'Algeria': 1532,
    'Angola': 1529,
    'Benin': 1516,
    'Botswana': 1510,
    'Burkina Faso': 1502,
    'Burundi': 1538,
    'Cameroon': 1530,
    'Cape Verde': 1536,
    'Central African Republic': 1543,
    'Chad': 1544,
    'Comoros': 1539,
    'Congo': 1540,
    'Congo DR': 1497,
    'DR Congo': 1497,
    'Djibouti': 1542,
    'Egypt': 32,
    'Equatorial Guinea': 1521,
    'Eritrea': 1545,
    'Eswatini': 1546,
    'Ethiopia': 1506,
    'Gabon': 1503,
    'Gambia': 1518,
    'Ghana': 1504,
    'Guinea': 1509,
    'Guinea-Bissau': 1520,
    'Ivory Coast': 1501,
    'Cote d\'Ivoire': 1501,
    'Kenya': 1511,
    'Lesotho': 1523,
    'Liberia': 1524,
    'Libya': 1526,
    'Madagascar': 1525,
    'Malawi': 1527,
    'Mali': 1500,
    'Mauritania': 1528,
    'Mauritius': 1505,
    'Morocco': 31,
    'Mozambique': 1548,
    'Namibia': 1549,
    'Niger': 1550,
    'Nigeria': 19,
    'Rwanda': 1551,
    'Sao Tome And Principe': 1552,
    'Senegal': 13,
    'Seychelles': 1553,
    'Sierra Leone': 1554,
    'Somalia': 1555,
    'South Africa': 1531,
    'South Sudan': 1556,
    'Sudan': 1557,
    'Tanzania': 1489,
    'Togo': 1534,
    'Tunisia': 28,
    'Uganda': 1519,
    'Zambia': 1507,
    'Zimbabwe': 1522,
    
    # EUROPE (UEFA) - Verified via API-Football Dec 2025
    'Albania': 778,
    'Andorra': 1091,
    'Armenia': 1092,
    'Austria': 775,
    'Azerbaijan': 1093,
    'Belarus': 1094,
    'Belgium': 1,
    'Bosnia': 1095,
    'Bosnia and Herzegovina': 1095,
    'Bosnia-Herzegovina': 1095,
    'Bulgaria': 1096,
    'Croatia': 3,
    'Cyprus': 1097,
    'Czech Republic': 770,
    'Czechia': 770,
    'Denmark': 21,
    'England': 10,
    'Estonia': 1098,
    'Faroe Islands': 1099,
    'Finland': 779,
    'France': 2,
    'Georgia': 1100,
    'Germany': 25,
    'Gibraltar': 1562,
    'Greece': 1117,
    'Hungary': 784,
    'Iceland': 786,
    'Ireland': 776,
    'Republic of Ireland': 776,
    'Israel': 24,
    'Italy': 768,
    'Kazakhstan': 1101,
    'Kosovo': 1564,
    'Latvia': 1102,
    'Liechtenstein': 1103,
    'Lithuania': 1104,
    'Luxembourg': 1105,
    'Malta': 1106,
    'Moldova': 1107,
    'Montenegro': 1109,
    'Netherlands': 1118,
    'North Macedonia': 1110,
    'FYR Macedonia': 1110,
    'Northern Ireland': 1113,
    'Norway': 1090,
    'Poland': 18,
    'Portugal': 27,
    'Romania': 780,
    'Russia': 4,
    'San Marino': 1111,
    'Scotland': 1108,
    'Serbia': 782,
    'Slovakia': 783,
    'Slovenia': 781,
    'Spain': 9,
    'Sweden': 5,
    'Switzerland': 15,
    'Turkey': 777,
    'Ukraine': 772,
    'Wales': 1119,
    
    # SOUTH AMERICA (CONMEBOL) - Verified via API-Football Dec 2025
    'Argentina': 26,
    'Bolivia': 2381,
    'Brazil': 6,
    'Chile': 2383,
    'Colombia': 8,
    'Ecuador': 2382,
    'Paraguay': 2380,
    'Peru': 30,
    'Uruguay': 7,
    'Venezuela': 2379,
    
    # NORTH/CENTRAL AMERICA (CONCACAF) - Verified via API-Football Dec 2025
    'Belize': 1583,
    'Canada': 5529,
    'Costa Rica': 29,
    'Cuba': 1584,
    'Curacao': 1585,
    'Dominican Republic': 1586,
    'El Salvador': 1587,
    'Guatemala': 1588,
    'Haiti': 1589,
    'Honduras': 4672,
    'Jamaica': 2385,
    'Mexico': 16,
    'Nicaragua': 1592,
    'Panama': 11,
    'Puerto Rico': 1593,
    'Suriname': 1594,
    'Trinidad and Tobago': 1600,
    'Trinidad And Tobago': 1600,
    'USA': 2384,
    'United States': 2384,
    
    # ASIA (AFC) - Verified via API-Football Dec 2025
    'Australia': 20,
    'Bahrain': 1559,
    'China': 1560,
    'China PR': 1560,
    'India': 1561,
    'Indonesia': 1568,
    'Iran': 22,
    'Iraq': 1572,
    'Japan': 12,
    'Jordan': 1573,
    'Korea Republic': 17,
    'South Korea': 17,
    'Kuwait': 1574,
    'Lebanon': 1575,
    'Malaysia': 1576,
    'Oman': 1577,
    'Palestine': 1578,
    'Philippines': 1579,
    'Qatar': 1569,
    'Saudi Arabia': 23,
    'Singapore': 1580,
    'Syria': 1581,
    'Thailand': 1582,
    'United Arab Emirates': 1566,
    'UAE': 1566,
    'Uzbekistan': 1570,
    'Vietnam': 1567,
    
    # OCEANIA (OFC) - Verified via API-Football Dec 2025
    'Fiji': 5160,
    'New Caledonia': 2538,
    'New Zealand': 4673,
    'Papua New Guinea': 2539,
    'Solomon Islands': 2540,
    'Tahiti': 2541,
    'Vanuatu': 2542,
}

def construct_logo_url(api_football_team_id: int) -> str:
    """Construct logo URL for national team"""
    return f"https://media.api-sports.io/football/teams/{api_football_team_id}.png"


def fix_international_logos():
    """Update logo URLs for international/national teams"""
    conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT DISTINCT t.team_id, t.name, t.logo_url, t.api_football_team_id
            FROM teams t
            JOIN fixtures f ON (t.team_id = f.home_team_id OR t.team_id = f.away_team_id)
            WHERE f.league_id IN (1, 4, 6, 9, 29, 30, 31, 32, 33, 34)
               OR f.league_name ILIKE '%world%cup%'
               OR f.league_name ILIKE '%africa%cup%'
               OR f.league_name ILIKE '%euro%'
               OR f.league_name ILIKE '%copa%america%'
               OR f.league_name ILIKE '%nations%'
        """)
        
        national_teams = cursor.fetchall()
        logger.info(f"Found {len(national_teams)} national teams in international competitions")
        
        updated = 0
        skipped = 0
        
        for team_id, name, current_logo, current_api_id in national_teams:
            normalized_name = name.strip()
            
            if normalized_name in NATIONAL_TEAM_ID_MAP:
                correct_api_id = NATIONAL_TEAM_ID_MAP[normalized_name]
                correct_logo = construct_logo_url(correct_api_id)
                
                if current_logo != correct_logo:
                    cursor.execute("""
                        UPDATE teams
                        SET logo_url = %s,
                            logo_last_synced_at = NOW(),
                            updated_at = NOW()
                        WHERE team_id = %s
                    """, (correct_logo, team_id))
                    
                    logger.info(f"  Updated: {name} -> Logo: {correct_logo}")
                    updated += 1
                else:
                    skipped += 1
            else:
                skipped += 1
        
        conn.commit()
        logger.info(f"\nSummary: Updated {updated}, Skipped {skipped}")
        
        return {'updated': updated, 'skipped': skipped}
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Error fixing logos: {e}", exc_info=True)
        raise
    finally:
        cursor.close()
        conn.close()


def check_missing_international_logos():
    """Check for international teams still missing logos"""
    conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT DISTINCT t.team_id, t.name, t.logo_url
            FROM teams t
            JOIN fixtures f ON (t.team_id = f.home_team_id OR t.team_id = f.away_team_id)
            WHERE (f.league_id IN (1, 4, 6, 9, 29, 30, 31, 32, 33, 34)
               OR f.league_name ILIKE '%world%cup%'
               OR f.league_name ILIKE '%africa%cup%'
               OR f.league_name ILIKE '%euro%'
               OR f.league_name ILIKE '%nations%')
              AND (t.logo_url IS NULL OR t.logo_url = '')
        """)
        
        missing = cursor.fetchall()
        
        if missing:
            logger.warning(f"Still missing logos for {len(missing)} national teams:")
            for team_id, name, logo in missing:
                logger.warning(f"  - {name} (team_id: {team_id})")
        else:
            logger.info("All international teams have logos!")
            
        return missing
        
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    logger.info("="*60)
    logger.info("FIXING INTERNATIONAL TEAM LOGOS")
    logger.info("="*60)
    
    result = fix_international_logos()
    
    logger.info("\n" + "="*60)
    logger.info("CHECKING FOR REMAINING MISSING LOGOS")
    logger.info("="*60)
    
    missing = check_missing_international_logos()
    
    if missing:
        logger.warning(f"\n{len(missing)} teams still need logos - add them to NATIONAL_TEAM_ID_MAP")
