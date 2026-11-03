module miter (
  input  [  0:0] \__pi_clk ,
  input  [ 10:0] \__pi_ctrl_in__26_16 ,
  input  [ 19:0] \__pi_data_in__39_20 ,
  input  [  0:0] \__pi_en ,
  input  [  0:0] \__pi_rst ,
`ifdef DIRECT_CROSS_POINTS
`else
`endif
  output [  4:0] \__po_data_out__9_5__gold ,
  output [  4:0] \__po_data_out__9_5__gate
);
  \gold.pmux_case03_crossbar.data_out.5 gold (
    .\__pi_clk (\__pi_clk ),
    .\__pi_ctrl_in__26_16 (\__pi_ctrl_in__26_16 ),
    .\__pi_data_in__39_20 (\__pi_data_in__39_20 ),
    .\__pi_en (\__pi_en ),
    .\__pi_rst (\__pi_rst ),
`ifdef DIRECT_CROSS_POINTS
`else
`endif
    .\__po_data_out__9_5 (\__po_data_out__9_5__gold )
  );
  \gate.pmux_case03_crossbar.data_out.5 gate (
    .\__pi_clk (\__pi_clk ),
    .\__pi_ctrl_in__26_16 (\__pi_ctrl_in__26_16 ),
    .\__pi_data_in__39_20 (\__pi_data_in__39_20 ),
    .\__pi_en (\__pi_en ),
    .\__pi_rst (\__pi_rst ),
`ifdef DIRECT_CROSS_POINTS
`else
`endif
    .\__po_data_out__9_5 (\__po_data_out__9_5__gate )
  );
`ifdef ASSUME_DEFINED_INPUTS
  miter_def_prop #(1, "assume") \__pi_clk__assume (\__pi_clk );
  miter_def_prop #(11, "assume") \__pi_ctrl_in__26_16__assume (\__pi_ctrl_in__26_16 );
  miter_def_prop #(20, "assume") \__pi_data_in__39_20__assume (\__pi_data_in__39_20 );
  miter_def_prop #(1, "assume") \__pi_en__assume (\__pi_en );
  miter_def_prop #(1, "assume") \__pi_rst__assume (\__pi_rst );
`endif
`ifndef DIRECT_CROSS_POINTS
`endif
`ifdef CHECK_MATCH_POINTS
`endif
`ifdef CHECK_OUTPUTS
  miter_cmp_prop #(5, "assert") \__po_data_out__9_5__assert (\__po_data_out__9_5__gold , \__po_data_out__9_5__gate );
`endif
`ifdef COVER_DEF_CROSS_POINTS
  `ifdef DIRECT_CROSS_POINTS
  `else
  `endif
`endif
`ifdef COVER_DEF_GOLD_MATCH_POINTS
`endif
`ifdef COVER_DEF_GATE_MATCH_POINTS
`endif
`ifdef COVER_DEF_GOLD_OUTPUTS
  miter_def_prop #(5, "cover") \__po_data_out__9_5__gold_cover (\__po_data_out__9_5__gold );
`endif
`ifdef COVER_DEF_GATE_OUTPUTS
  miter_def_prop #(5, "cover") \__po_data_out__9_5__gate_cover (\__po_data_out__9_5__gate );
`endif
endmodule
module miter_cmp_prop #(parameter WIDTH=1, parameter TYPE="assert") (input [WIDTH-1:0] in_gold, in_gate);
  reg okay;
  integer i;
  always @* begin
    okay = 1;
    for (i = 0; i < WIDTH; i = i+1)
      okay = okay && (in_gold[i] === 1'bx || in_gold[i] === in_gate[i]);
  end
  generate
    if (TYPE == "assert") always @* assert(okay);
    if (TYPE == "assume") always @* assume(okay);
    if (TYPE == "cover")  always @* cover(okay);
  endgenerate
endmodule
module miter_def_prop #(parameter WIDTH=1, parameter TYPE="assert") (input [WIDTH-1:0] in);
  wire okay = ^in !== 1'bx;
  generate
    if (TYPE == "assert") always @* assert(okay);
    if (TYPE == "assume") always @* assume(okay);
    if (TYPE == "cover")  always @* cover(okay);
  endgenerate
endmodule
module \gold.pmux_case03_crossbar.data_out.5 (
  input  [  0:0] \__pi_clk ,
  input  [ 10:0] \__pi_ctrl_in__26_16 ,
  input  [ 19:0] \__pi_data_in__39_20 ,
  input  [  0:0] \__pi_en ,
  input  [  0:0] \__pi_rst ,
  output [  4:0] \__po_data_out__9_5
);
endmodule
module \gate.pmux_case03_crossbar.data_out.5 (
  input  [  0:0] \__pi_clk ,
  input  [ 10:0] \__pi_ctrl_in__26_16 ,
  input  [ 19:0] \__pi_data_in__39_20 ,
  input  [  0:0] \__pi_en ,
  input  [  0:0] \__pi_rst ,
  output [  4:0] \__po_data_out__9_5
);
endmodule
