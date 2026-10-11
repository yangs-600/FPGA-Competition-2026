// Missing PMUX codes use a default arm that directly references sel[3].
module default_ctrl_specialization(
    input [3:0] sel,
    input [7:0] b,
    output reg [7:0] y
);
always @* begin
    y = {8{sel[3]}};
    case (sel)
        4'd2: y = b;
        4'd0: y = b;
        4'd3: y = b;
        4'd1: y = b;
    endcase
end
endmodule
