module miter (
  input  [  0:0] \__pi_clk ,
  input  [  5:0] \__pi_ctrl_in__5_0 ,
  input  [  5:0] \__pi_ctrl_in__37_32 ,
  input  [ 11:0] \__pi_ctrl_in__59_48 ,
  input  [ 11:0] \__pi_data_in__11_0 ,
  input  [ 23:0] \__pi_data_in__47_24 ,
  input  [  2:0] \__pi_data_out__2_0 ,
  input  [  2:0] \__pi_data_out__8_6 ,
  input  [  0:0] \__pi_en ,
  input  [  0:0] \__pi_rst ,
`ifdef DIRECT_CROSS_POINTS
`else
`endif
  output [  2:0] \__po_data_out__11_9__gold ,
  output [  2:0] \__po_data_out__11_9__gate
);
  \gold.pmux_case02_pipeline.data_out.10 gold (
    .\__pi_clk (\__pi_clk ),
    .\__pi_ctrl_in__5_0 (\__pi_ctrl_in__5_0 ),
    .\__pi_ctrl_in__37_32 (\__pi_ctrl_in__37_32 ),
    .\__pi_ctrl_in__59_48 (\__pi_ctrl_in__59_48 ),
    .\__pi_data_in__11_0 (\__pi_data_in__11_0 ),
    .\__pi_data_in__47_24 (\__pi_data_in__47_24 ),
    .\__pi_data_out__2_0 (\__pi_data_out__2_0 ),
    .\__pi_data_out__8_6 (\__pi_data_out__8_6 ),
    .\__pi_en (\__pi_en ),
    .\__pi_rst (\__pi_rst ),
`ifdef DIRECT_CROSS_POINTS
`else
`endif
    .\__po_data_out__11_9 (\__po_data_out__11_9__gold )
  );
  \gate.pmux_case02_pipeline.data_out.10 gate (
    .\__pi_clk (\__pi_clk ),
    .\__pi_ctrl_in__5_0 (\__pi_ctrl_in__5_0 ),
    .\__pi_ctrl_in__37_32 (\__pi_ctrl_in__37_32 ),
    .\__pi_ctrl_in__59_48 (\__pi_ctrl_in__59_48 ),
    .\__pi_data_in__11_0 (\__pi_data_in__11_0 ),
    .\__pi_data_in__47_24 (\__pi_data_in__47_24 ),
    .\__pi_data_out__2_0 (\__pi_data_out__2_0 ),
    .\__pi_data_out__8_6 (\__pi_data_out__8_6 ),
    .\__pi_en (\__pi_en ),
    .\__pi_rst (\__pi_rst ),
`ifdef DIRECT_CROSS_POINTS
`else
`endif
    .\__po_data_out__11_9 (\__po_data_out__11_9__gate )
  );
`ifdef ASSUME_DEFINED_INPUTS
  miter_def_prop #(1, "assume") \__pi_clk__assume (\__pi_clk );
  miter_def_prop #(6, "assume") \__pi_ctrl_in__5_0__assume (\__pi_ctrl_in__5_0 );
  miter_def_prop #(6, "assume") \__pi_ctrl_in__37_32__assume (\__pi_ctrl_in__37_32 );
  miter_def_prop #(12, "assume") \__pi_ctrl_in__59_48__assume (\__pi_ctrl_in__59_48 );
  miter_def_prop #(12, "assume") \__pi_data_in__11_0__assume (\__pi_data_in__11_0 );
  miter_def_prop #(24, "assume") \__pi_data_in__47_24__assume (\__pi_data_in__47_24 );
  miter_def_prop #(3, "assume") \__pi_data_out__2_0__assume (\__pi_data_out__2_0 );
  miter_def_prop #(3, "assume") \__pi_data_out__8_6__assume (\__pi_data_out__8_6 );
  miter_def_prop #(1, "assume") \__pi_en__assume (\__pi_en );
  miter_def_prop #(1, "assume") \__pi_rst__assume (\__pi_rst );
`endif
`ifndef DIRECT_CROSS_POINTS
`endif
`ifdef CHECK_MATCH_POINTS
`endif
`ifdef CHECK_OUTPUTS
  miter_cmp_prop #(3, "assert") \__po_data_out__11_9__assert (\__po_data_out__11_9__gold , \__po_data_out__11_9__gate );
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
  miter_def_prop #(3, "cover") \__po_data_out__11_9__gold_cover (\__po_data_out__11_9__gold );
`endif
`ifdef COVER_DEF_GATE_OUTPUTS
  miter_def_prop #(3, "cover") \__po_data_out__11_9__gate_cover (\__po_data_out__11_9__gate );
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
module \gold.pmux_case02_pipeline.data_out.10 (
  input  [  0:0] \__pi_clk ,
  input  [  5:0] \__pi_ctrl_in__5_0 ,
  input  [  5:0] \__pi_ctrl_in__37_32 ,
  input  [ 11:0] \__pi_ctrl_in__59_48 ,
  input  [ 11:0] \__pi_data_in__11_0 ,
  input  [ 23:0] \__pi_data_in__47_24 ,
  input  [  2:0] \__pi_data_out__2_0 ,
  input  [  2:0] \__pi_data_out__8_6 ,
  input  [  0:0] \__pi_en ,
  input  [  0:0] \__pi_rst ,
  output [  2:0] \__po_data_out__11_9
);
endmodule
module \gate.pmux_case02_pipeline.data_out.10 (
  input  [  0:0] \__pi_clk ,
  input  [  5:0] \__pi_ctrl_in__5_0 ,
  input  [  5:0] \__pi_ctrl_in__37_32 ,
  input  [ 11:0] \__pi_ctrl_in__59_48 ,
  input  [ 11:0] \__pi_data_in__11_0 ,
  input  [ 23:0] \__pi_data_in__47_24 ,
  input  [  2:0] \__pi_data_out__2_0 ,
  input  [  2:0] \__pi_data_out__8_6 ,
  input  [  0:0] \__pi_en ,
  input  [  0:0] \__pi_rst ,
  output [  2:0] \__po_data_out__11_9
);
endmodule
