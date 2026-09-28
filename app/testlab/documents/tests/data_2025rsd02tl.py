"""2025RSD02TL TCN001, transcribed from the hidden DataBase sheet of
reference/Testlab Data Program 2026RSD06TL.xlsm (columns named as in Excel).

Excel arrangement 1 = single seal + Plug Seal: the IB columns hold the Plug
Seal, the OB columns the Test Seal. The workbook has no Plug Seal
conditions and no flush/barrier values. Used by AT-3."""

ARRANGEMENT = '1'

ROW = {
    'ProjName': 'ACWA / DHTW 4.750',
    'TestRunDescription': '• Pre-test work Job & Plug seal, required on stationary and rotating seal faces.\n   - Waviness measurement on 1 location\n   - Taper measurement on 2 locations\n   - Roughness measurement\n   - Profile measurement\n   - Height stationary face (only carbon)\n• Install mechanical seals per drawing F001842744_2 (Plug) / F001256462_2 (Job)\n   - Use soft face backing rings C100057354 (dwg F001172856)\n   - Install thermocouple at plug seal stationary face.\n• Pressurize to indicated pressure, measure break-out torque. Repeat torque measurements after 10 minutes.\n• Start Test Unit\n• Stop test unit and measure break-out torque. Repeat torque measurements after 10 minutes.\n• Post-test work Job and plug seal, required on stationary and rotating seal faces.\n   - Waviness measurement on 1 location\n   - Taper measurement on 2 locations\n   - Roughness measurement\n   - Profile measurement\n   - Height stationary face (only carbon)',
    'TestUnit': 'B',
    'Speed': '1100',
    'By': 'MG',
    'RefDwg': 'F001842744_2 / F001256462_2',
    'Duration': '50',
    'IBSealType': 'DHTW 4.750',
    'IBStatFace': 'C0625623AP',
    'IBRotFace': 'C0625624SL - WAVY',
    'IBSpring': '668818NL (18)',
    'OBSealType': 'DHTW 4.750',
    'OBStatFace': 'C0625623AP',
    'OBRotFace': 'C0625624SL - WAVY',
    'OBSpring': '668818NL (16)',
    'Product': 'Water',
    'ProdPress': '80',
    'ProdTemp': '40°C',
    'ProdFlow': 'TBD',
    'Bar/Buf': '',
    'Bar/BufPress': '',
    'Bar/BufTemp': '',
    'Bar/BufFlow': '',
}
