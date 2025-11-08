A way to use Jetson Pinmux Template on Linux with out needing to use Microsoft Excel.

Download *.py

Download Jetson_Thor_Series_Modules_Pinmux_Template.xlsm from
```
https://developer.nvidia.com/downloads/assets/embedded/secure/jetson/thor/docs/Jetson_Thor_Series_Modules_Pinmux_Template.xlsm
```

### To enable macros/vba in LibreOffice Calc for an .xls* files:

- Open **Jetson_Thor_Series_Modules_Pinmux_Template_v1.4.xlsm** with **LibreOffice Calc**.
- Go to **Tools → Options** → **LibreOffice → Security** → click **Macro Security** → select the **Trusted Sources** tab.
- Under **Trusted File Locations**, click **Add**, then select the directory where you saved `Jetson_Thor_Series_Modules_Pinmux_Template_v1.4.xlsm`.
- Exit LibreOffice Calc.


pip install pandas openpyxl

```
# 1. Generate base dtsi.
python3 gen_pinmux_dt_from_xlsx.py Jetson_Thor_Series_Modules_Pinmux_Template_v1.4.xlsm -o pinmux-thor-Before.dtsi

# 2. In Calc make your edits to Jetson_Thor_Series_Modules_Pinmux_Template.xlsm
Click Save, Click bottom right box titled "Use Excel 2007-365 (macro-enabled) Format"

# 3. Generate after dtsi 
python3 gen_pinmux_dt_from_xlsx.py Jetson_Thor_Series_Modules_Pinmux_Template_v1.4.xlsm -o pinmux-thor-After.dtsi

# 4. Produce a delta .dtsi with the required changed pins
python3 pinmux_dtsi_delta.py pinmux-thor-Before.dtsi pinmux-thor-After.dtsi -o pinmux-thor-Delta.dtsi
```

