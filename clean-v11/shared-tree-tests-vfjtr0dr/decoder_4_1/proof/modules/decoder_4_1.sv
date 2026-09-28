module miter (
  input  [127:0] \__pi_data ,
  input  [  3:0] \__pi_sel ,
`ifdef DIRECT_CROSS_POINTS
`else
`endif
  output [  7:0] \__po_y__gold ,
  output [  7:0] \__po_z__gold ,
  output [  7:0] \__po_y__gate ,
  output [  7:0] \__po_z__gate
);
  \gold.decoder_4_1 gold (
    .\__pi_data (\__pi_data ),
    .\__pi_sel (\__pi_sel ),
`ifdef DIRECT_CROSS_POINTS
`else
`endif
    .\__po_y (\__po_y__gold ),
    .\__po_z (\__po_z__gold )
  );
  \gate.decoder_4_1 gate (
    .\__pi_data (\__pi_data ),
    .\__pi_sel (\__pi_sel ),
`ifdef DIRECT_CROSS_POINTS
`else
`endif
    .\__po_y (\__po_y__gate ),
    .\__po_z (\__po_z__gate )
  );
`ifdef ASSUME_DEFINED_INPUTS
  miter_def_prop #(128, "assume") \__pi_data__assume (\__pi_data );
  miter_def_prop #(4, "assume") \__pi_sel__assume (\__pi_sel );
`endif
`ifndef DIRECT_CROSS_POINTS
`endif
`ifdef CHECK_MATCH_POINTS
`endif
`ifdef CHECK_OUTPUTS
  miter_cmp_prop #(8, "assert") \__po_y__assert (\__po_y__gold , \__po_y__gate );
  miter_cmp_prop #(8, "assert") \__po_z__assert (\__po_z__gold , \__po_z__gate );
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
  miter_def_prop #(8, "cover") \__po_y__gold_cover (\__po_y__gold );
  miter_def_prop #(8, "cover") \__po_z__gold_cover (\__po_z__gold );
`endif
`ifdef COVER_DEF_GATE_OUTPUTS
  miter_def_prop #(8, "cover") \__po_y__gate_cover (\__po_y__gate );
  miter_def_prop #(8, "cover") \__po_z__gate_cover (\__po_z__gate );
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
module \gold.decoder_4_1 (
  input  [127:0] \__pi_data ,
  input  [  3:0] \__pi_sel ,
  output [  7:0] \__po_y ,
  output [  7:0] \__po_z
);
endmodule
module \gate.decoder_4_1 (
  input  [127:0] \__pi_data ,
  input  [  3:0] \__pi_sel ,
  output [  7:0] \__po_y ,
  output [  7:0] \__po_z
);
endmodule
