module miter (
  input  [ 63:0] \__pi_data ,
  input  [  2:0] \__pi_sel ,
`ifdef DIRECT_CROSS_POINTS
`else
`endif
  output [  7:0] \__po_z__gold ,
  output [  7:0] \__po_z__gate
);
  \gold.decoder_3_0.z gold (
    .\__pi_data (\__pi_data ),
    .\__pi_sel (\__pi_sel ),
`ifdef DIRECT_CROSS_POINTS
`else
`endif
    .\__po_z (\__po_z__gold )
  );
  \gate.decoder_3_0.z gate (
    .\__pi_data (\__pi_data ),
    .\__pi_sel (\__pi_sel ),
`ifdef DIRECT_CROSS_POINTS
`else
`endif
    .\__po_z (\__po_z__gate )
  );
`ifdef ASSUME_DEFINED_INPUTS
  miter_def_prop #(64, "assume") \__pi_data__assume (\__pi_data );
  miter_def_prop #(3, "assume") \__pi_sel__assume (\__pi_sel );
`endif
`ifndef DIRECT_CROSS_POINTS
`endif
`ifdef CHECK_MATCH_POINTS
`endif
`ifdef CHECK_OUTPUTS
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
  miter_def_prop #(8, "cover") \__po_z__gold_cover (\__po_z__gold );
`endif
`ifdef COVER_DEF_GATE_OUTPUTS
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
module \gold.decoder_3_0.z (
  input  [ 63:0] \__pi_data ,
  input  [  2:0] \__pi_sel ,
  output [  7:0] \__po_z
);
endmodule
module \gate.decoder_3_0.z (
  input  [ 63:0] \__pi_data ,
  input  [  2:0] \__pi_sel ,
  output [  7:0] \__po_z
);
endmodule
