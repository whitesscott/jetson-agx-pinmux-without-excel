Create dts{i} using Jetson Pinmux Template on Linux with out Microsoft Excel.

Download a new Jetson_Thor_Series_Modules_Pinmux_Template.xlsm from
```
https://developer.nvidia.com/downloads/assets/embedded/secure/jetson/thor/docs/Jetson_Thor_Series_Modules_Pinmux_Template.xlsm
```
Install requirments.
```
pip install pandas openpyxl
```
Copy the three files to an empty directory.
```
cp ~/Downloads/Jetson_Thor_Series_Modules_Pinmux_Template_v1.4.xlsm ~/emptyDir
cp *.py ~/emptyDir
```
Then
```
# 1. Generate base dtsi.
python gen_pinmux_dt_from_xlsx.py Jetson_Thor_Series_Modules_Pinmux_Template_v1.4.xlsm -o Before.dtsi

# 2. Doubleclick Pinmux xlsm to open in Calc. Make your edits to Jetson_Thor_Series_Modules_Pinmux_Template.xlsm
Click Save, Click bottom right box titled "Use Excel 2007-365 (macro-enabled) Format"
Exit LibreOffice.

# 3. Generate after dtsi 
python gen_pinmux_dt_from_xlsx.py Jetson_Thor_Series_Modules_Pinmux_Template_v1.4.xlsm -o After.dtsi

# 4. Produce a delta .dtsi with the required changed pins
python Pinmux_dtsi_delta.py Before.dtsi After.dtsi -o pinmux-thor-Delta.dtsi
```
