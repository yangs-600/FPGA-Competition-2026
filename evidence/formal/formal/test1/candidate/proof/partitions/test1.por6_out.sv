module miter (
  input  [  0:0] \__pi_clock ,
  input  [  0:0] \__pi_reset ,
  input  [  0:0] \__pi_valid ,
`ifdef DIRECT_CROSS_POINTS
`else
`endif
  output [  0:0] \__po_por6_out__gold ,
  output [  0:0] \__po_por6_out__gate
);
  \gold.test1.por6_out gold (
    .\__pi_clock (\__pi_clock ),
    .\__pi_reset (\__pi_reset ),
    .\__pi_valid (\__pi_valid ),
`ifdef DIRECT_CROSS_POINTS
`else
`endif
    .\__po_por6_out (\__po_por6_out__gold )
  );
  \gate.test1.por6_out gate (
    .\__pi_clock (\__pi_clock ),
    .\__pi_reset (\__pi_reset ),
    .\__pi_valid (\__pi_valid ),
`ifdef DIRECT_CROSS_POINTS
`else
`endif
    .\__po_por6_out (\__po_por6_out__gate )
  );
`ifdef ASSUME_DEFINED_INPUTS
  miter_def_prop #(1, "assume") \__pi_clock__assume (\__pi_clock );
  miter_def_prop #(1, "assume") \__pi_reset__assume (\__pi_reset );
  miter_def_prop #(1, "assume") \__pi_valid__assume (\__pi_valid );
`endif
`ifndef DIRECT_CROSS_POINTS
`endif
`ifdef CHECK_MATCH_POINTS
`endif
`ifdef CHECK_OUTPUTS
  miter_cmp_prop #(1, "assert") \__po_por6_out__assert (\__po_por6_out__gold , \__po_por6_out__gate );
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
  miter_def_prop #(1, "cover") \__po_por6_out__gold_cover (\__po_por6_out__gold );
`endif
`ifdef COVER_DEF_GATE_OUTPUTS
  miter_def_prop #(1, "cover") \__po_por6_out__gate_cover (\__po_por6_out__gate );
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
module \gold.test1.por6_out (
  input  [  0:0] \__pi_clock ,
  input  [  0:0] \__pi_reset ,
  input  [  0:0] \__pi_valid ,
  output [  0:0] \__po_por6_out
);
endmodule
module \gate.test1.por6_out (
  input  [  0:0] \__pi_clock ,
  input  [  0:0] \__pi_reset ,
  input  [  0:0] \__pi_valid ,
  output [  0:0] \__po_por6_out
);
endmodule
