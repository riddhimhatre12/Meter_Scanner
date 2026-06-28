with open(r'd:\Riddhi\Meter_Scanner\templates\dashboard.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Remove the old duplicate style block that sits outside <style> tags
# It starts right after </style> (first one ends at ~line 183) and ends at </style> (second tag)
import re

# Find the second </style> which ends the old block
# Strategy: after the first </style>, remove everything up to and NOT including the <div class="dashboard-container">
first_style_end = content.find('</style>') + len('</style>')
dashboard_div = content.find('<div class="dashboard-container">')

if first_style_end != -1 and dashboard_div != -1:
    # Remove the junk CSS floating between the two style blocks
    junk = content[first_style_end:dashboard_div]
    # Find if there's a second </style> in the junk
    second_style_end_in_junk = junk.rfind('</style>')
    if second_style_end_in_junk != -1:
        # Remove from first_style_end to second_style_end in junk
        remove_end = first_style_end + second_style_end_in_junk + len('</style>')
        content = content[:first_style_end] + '\n\n' + content[remove_end:]
        print("Removed old CSS block")
    else:
        print("No second </style> found in junk section")
else:
    print(f"Markers: style_end={first_style_end}, div={dashboard_div}")

with open(r'd:\Riddhi\Meter_Scanner\templates\dashboard.html', 'w', encoding='utf-8') as f:
    f.write(content)
print(f"Done. File size: {len(content)}")
